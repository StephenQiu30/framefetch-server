"""Persistent per-site Chromium profiles driven through Playwright.

Each site owns ``<root>/<site>``. A profile is opened only for one operation
and closed afterwards; nothing but the broker's RPC ever starts a browser.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from http.cookiejar import Cookie
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.integrations.site_session_catalog import SiteTarget, site_target
from app.services.site_sessions import HeaderPlugin, LoginProbe
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.netscape_cookie import (
    is_allowed_domain,
    parse_cookie_payload,
    serialize_cookies,
)
from app.workers.session.contracts import BrowserOutcome
from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    Route,
)
from playwright.async_api import (
    Error as PlaywrightError,
)

OPERATION_TIMEOUT_SECONDS = 60
_CHALLENGE_STATUSES = frozenset({403, 429})
_YOUTUBE_LOGGED_IN = "() => window.ytcfg?.get?.('LOGGED_IN') ?? null"
_DOUYIN_PROFILE = """
async () => {
  try {
    const path = '/aweme/v1/web/user/profile/self/';
    const response = await fetch(path + '?device_platform=webapp&aid=6383', {
      credentials: 'include', signal: AbortSignal.timeout(15000)
    });
    if (!response.ok) return null;
    const data = await response.json();
    if (data.status_code === 0 && data.user?.uid && data.user.uid !== '0') return true;
    if (data.status_code === 8) return false;
    return null;
  } catch (_) { return null; }
}
"""
# Ported from the host Yuanbao session: identity lives in localStorage and the
# page's own API produces the per-request headers WeChat Channels parsing needs.
_YUANBAO_AUTH = """
async () => {
  if (location.origin !== 'https://yuanbao.tencent.com') return {};
  const auth = {
    userId: localStorage.getItem('yb_user_id') || '',
    token: localStorage.getItem('yb_token') || ''
  };
  if (!auth.userId || !auth.token) {
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index) || '';
      if (!key.startsWith('LOCAL_AUTH_INFO_KEY_')) continue;
      try {
        const value = JSON.parse(localStorage.getItem(key) || '{}');
        if (value.userId && value.token) Object.assign(auth, value);
      } catch (_) {}
    }
  }
  let headers = {};
  if (window.$webApi?.getYbCommonHeaders) {
    headers = await window.$webApi.getYbCommonHeaders();
  }
  if (window.$webApi?.setContextualRequestHeaders) {
    const request = {url: '/api/weixin/get_parse_result', headers};
    await window.$webApi.setContextualRequestHeaders(request);
    headers = request.headers;
  }
  return {userId: auth.userId, token: auth.token, headers};
}
"""


class HeadersUnavailable(Exception):
    """The site is not logged in, so no request headers can be produced."""


@dataclass(frozen=True, slots=True)
class VisitResult:
    outcome: BrowserOutcome
    error_code: str | None = None
    jar: bytes | None = None


class SiteBrowser:
    def __init__(
        self,
        playwright: Playwright,
        root: Path,
        *,
        proxy: str | None,
        provider_proxies: Mapping[str, str] | None = None,
    ) -> None:
        self._playwright = playwright
        self._root = root
        self._proxy = proxy
        self._provider_proxies = dict(provider_proxies or {})
        self._locks: dict[str, asyncio.Lock] = {}

    async def bootstrap(self, site: str, jar: bytes) -> VisitResult:
        target = site_target(site)
        cookies = _to_playwright(jar, target)
        async with self._open(site, create=True) as context:
            await context.clear_cookies()
            await context.add_cookies(cookies)
            return await self._visit(context, target)

    async def keepalive(self, site: str) -> VisitResult:
        target = site_target(site)
        if not self._profile(site).is_dir():
            return VisitResult(BrowserOutcome.PROFILE_MISSING)
        async with self._open(site, create=False) as context:
            return await self._visit(context, target)

    async def headers(self, site: str) -> bytes:
        target = site_target(site)
        if target.policy.header_plugin is not HeaderPlugin.YUANBAO:
            raise HeadersUnavailable(site)
        if not self._profile(site).is_dir():
            raise HeadersUnavailable(site)
        async with self._open(site, create=False) as context:
            page = await self._page(context, target)
            await page.goto(target.policy.keepalive_url, wait_until="load")
            auth = await page.evaluate(_YUANBAO_AUTH)
        payload = _yuanbao_payload(auth)
        if payload is None:
            raise HeadersUnavailable(site)
        return payload

    async def forget(self, site: str) -> None:
        site_target(site)  # reject anything that is not a valid session key
        async with self._lock(site):
            await asyncio.to_thread(shutil.rmtree, self._profile(site), True)

    # Internals --------------------------------------------------------------

    def _profile(self, site: str) -> Path:
        return self._root / site

    def _lock(self, site: str) -> asyncio.Lock:
        return self._locks.setdefault(site, asyncio.Lock())

    def _open(self, site: str, *, create: bool) -> _ProfileContext:
        return _ProfileContext(self, site, create=create)

    async def _launch(self, site: str, *, create: bool) -> BrowserContext:
        profile = self._profile(site)
        if create:
            profile.mkdir(mode=0o700, parents=True, exist_ok=True)
        policy = site_target(site).policy
        proxy = self._provider_proxies.get(str(policy.provider_key), self._proxy)
        context = await self._playwright.chromium.launch_persistent_context(
            profile,
            headless=True,
            proxy=None if proxy is None else {"server": proxy},
            locale="zh-CN",
        )
        context.set_default_timeout(OPERATION_TIMEOUT_SECONDS * 1000)
        return context

    async def _visit(self, context: BrowserContext, target: SiteTarget) -> VisitResult:
        policy = target.policy
        try:
            page = await self._page(context, target)
            response = await page.goto(policy.keepalive_url, wait_until="load")
            if response is not None and response.status in _CHALLENGE_STATUSES:
                return VisitResult(
                    BrowserOutcome.TEMPORARY_FAILURE,
                    "provider_rate_limited"
                    if response.status == 429
                    else "egress_challenged",
                )
            logged_in = await self._logged_in(page, context, target)
            jar = await _export(context, target)
        except PlaywrightError:
            return VisitResult(BrowserOutcome.UNAVAILABLE)
        if logged_in is None:
            return VisitResult(
                BrowserOutcome.TEMPORARY_FAILURE, "login_probe_inconclusive"
            )
        if not logged_in:
            return VisitResult(BrowserOutcome.LOGGED_OUT, "session_logged_out")
        return VisitResult(BrowserOutcome.VERIFIED, jar=jar)

    async def _logged_in(
        self, page: Page, context: BrowserContext, target: SiteTarget
    ) -> bool | None:
        policy = target.policy
        if policy.header_plugin is HeaderPlugin.YUANBAO:
            return _yuanbao_payload(await page.evaluate(_YUANBAO_AUTH)) is not None
        if policy.login_probe in {
            LoginProbe.YOUTUBE_LOGGED_IN,
            LoginProbe.DOUYIN_PROFILE,
        }:
            probe = (
                _YOUTUBE_LOGGED_IN
                if policy.login_probe is LoginProbe.YOUTUBE_LOGGED_IN
                else _DOUYIN_PROFILE
            )
            result = await page.evaluate(probe)
            return result if isinstance(result, bool) else None
        # Cookie presence is not proof of a logged-in identity.
        return None

    async def _page(self, context: BrowserContext, target: SiteTarget) -> Page:
        page = context.pages[0] if context.pages else await context.new_page()
        allowed = {
            *target.cookie_domains,
            urlsplit(target.policy.keepalive_url).hostname,
        }

        async def guard(route: Route) -> None:
            request = route.request
            host = urlsplit(request.url).hostname or ""
            if (
                request.is_navigation_request()
                and request.frame == page.main_frame
                and not is_allowed_domain(host, {item for item in allowed if item})
            ):
                await route.abort("blockedbyclient")
                return
            await route.continue_()

        await page.route("**/*", guard)
        return page


class _ProfileContext:
    """Serialize one site's profile and always close the browser."""

    def __init__(self, browser: SiteBrowser, site: str, *, create: bool) -> None:
        self._browser, self._site, self._create = browser, site, create
        self._context: BrowserContext | None = None

    async def __aenter__(self) -> BrowserContext:
        await self._browser._lock(self._site).acquire()
        try:
            self._context = await self._browser._launch(self._site, create=self._create)
        except BaseException:
            self._browser._lock(self._site).release()
            raise
        return self._context

    async def __aexit__(self, *exc: object) -> None:
        try:
            if self._context is not None:
                await self._context.close()
        finally:
            self._browser._lock(self._site).release()


def _to_playwright(jar: bytes, target: SiteTarget) -> list[Any]:
    try:
        lines = parse_cookie_payload(jar, target.cookie_domains)
    except RunnerFailure as exc:
        raise ValueError("invalid site session jar") from exc
    cookies = []
    for line in lines:
        domain, _, path, secure, expires, name, value = (
            field.decode() for field in line.line.split(b"\t")
        )
        http_only = domain.startswith("#HttpOnly_")
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": domain.removeprefix("#HttpOnly_"),
                "path": path,
                "expires": int(expires) if int(expires) > 0 else -1,
                "httpOnly": http_only,
                "secure": secure == "TRUE",
            }
        )
    return cookies


async def _export(context: BrowserContext, target: SiteTarget) -> bytes:
    cookies = [
        cookie
        for cookie in await context.cookies()
        if cookie.get("value")
        and is_allowed_domain(cookie["domain"], target.cookie_domains)
    ]
    cookies.sort(key=lambda item: (item["domain"], item["path"], item["name"]))
    return serialize_cookies(_cookie(item) for item in cookies)


def _cookie(raw: Any) -> Cookie:
    domain = raw["domain"]
    expires = int(raw["expires"]) if raw.get("expires", -1) > 0 else None
    return Cookie(
        0,
        raw["name"],
        raw["value"],
        None,
        False,
        domain,
        True,
        domain.startswith("."),
        raw["path"],
        True,
        bool(raw.get("secure")),
        expires,
        expires is None,
        None,
        None,
        {"HttpOnly": ""} if raw.get("httpOnly") else {},
        False,
    )


def _yuanbao_payload(auth: object) -> bytes | None:
    """Pass the page's identity through; the Runner applies its header allowlist."""
    if not isinstance(auth, dict):
        return None
    user, token = auth.get("userId"), auth.get("token")
    if not (isinstance(user, str) and user and isinstance(token, str) and token):
        return None
    headers = auth.get("headers")
    return json.dumps(
        {
            "userId": user,
            "token": token,
            "headers": headers if isinstance(headers, dict) else {},
        },
        separators=(",", ":"),
    ).encode()
