"""Dedicated per-site browser profiles; no reads from the user's daily browser.

Only Chromium owns its profile format. There is no application cookie database,
task journal, background navigation, or account keepalive.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from http.cookiejar import Cookie
from pathlib import Path
from typing import TYPE_CHECKING

from app.integrations.site_session_catalog import known_session_sites, site_target
from app.workers.runner.netscape_cookie import (
    has_safe_cookie_fields,
    is_allowed_domain,
    serialize_cookies,
)
from app.workers.runner.provider_session_files import prepare_private_root
from app.workers.session.page_headers import page_headers

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Playwright


class SourceUnavailable(Exception):
    """Stable public codes only: browser diagnostics may contain private URLs."""

    def __init__(self, code: str = "provider_session_not_ready") -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    site: str
    generation: int
    cookies: bytes = field(repr=False)
    headers: bytes | None = field(default=None, repr=False)


class BrowserSource:
    def __init__(self, root: Path, *, proxy: str, secret: bytes) -> None:
        self.root = root
        self.proxy = proxy
        self._secret = secret
        self._instance = secrets.token_bytes(32)
        self._playwright: Playwright | None = None
        self._lock_fd: int | None = None
        self._locks = {site: asyncio.Lock() for site in known_session_sites()}
        self._logins: dict[str, BrowserContext] = {}
        self._login_timers: dict[str, asyncio.Task[None]] = {}
        self._slots = asyncio.Semaphore(4)
        self._login_lock = asyncio.Lock()

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        prepare_private_root(self.root)
        descriptor = os.open(
            self.root / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_fd = descriptor
            self._playwright = await async_playwright().start()
        except BaseException:
            self._lock_fd = None
            os.close(descriptor)
            raise

    def _site(self, site: str) -> None:
        if site not in self._locks:
            raise SourceUnavailable("provider_session_not_allowed")

    async def _launch(self, site: str, *, visible: bool) -> BrowserContext:
        self._site(site)
        if self._playwright is None:
            raise SourceUnavailable()
        directory = self.root / site
        prepare_private_root(directory)
        from app.services.site_sessions import HeaderPlugin
        from app.workers.session.page_headers import PAGE_USER_AGENT

        policy = site_target(site).policy
        # Page-signed Yuanbao requests must match the existing extractor UA.
        user_agent = (
            PAGE_USER_AGENT if policy.header_plugin is HeaderPlugin.YUANBAO else None
        )
        try:
            async with asyncio.timeout(25):
                return await self._playwright.chromium.launch_persistent_context(
                    str(directory),
                    headless=not visible,
                    chromium_sandbox=True,
                    env={
                        key: value
                        for key, value in os.environ.items()
                        if key
                        in {
                            "PATH",
                            "HOME",
                            "TMPDIR",
                            "LANG",
                            "LC_ALL",
                            "DISPLAY",
                            "XAUTHORITY",
                        }
                    },
                    proxy={"server": self.proxy},
                    user_agent=user_agent,
                    args=[
                        "--proxy-bypass-list=<-loopback>",
                        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                    ],
                    timeout=20_000,
                )
        except Exception:
            raise SourceUnavailable() from None

    @asynccontextmanager
    async def _context(self, site: str) -> AsyncIterator[BrowserContext]:
        existing = self._logins.get(site)
        if existing is not None:
            if existing.pages:
                yield existing
                return
            await self._close_login(site)
        async with self._slots:
            context = await self._launch(site, visible=False)
            try:
                yield context
            finally:
                await context.close()

    async def read(self, site: str, *, include_headers: bool = False) -> SourceSnapshot:
        self._site(site)
        target = site_target(site)
        try:
            async with asyncio.timeout(60), self._locks[site]:
                async with self._context(site) as context:
                    values = await context.cookies()
                    cookies = tuple(
                        _cookie(value)
                        for value in values
                        if is_allowed_domain(value["domain"], target.cookie_domains)
                        and value["value"]
                        and (value["expires"] <= 0 or value["expires"] > time.time())
                    )
                    cookies = tuple(c for c in cookies if has_safe_cookie_fields(c))
                    if not target.policy.accepts(frozenset(c.name for c in cookies)):
                        raise SourceUnavailable("credential_required")
                    headers = (
                        await page_headers(target.policy, cookies, context)
                        if include_headers
                        else None
                    )
                    # No platform identity endpoint is assumed. Conservatively
                    # invalidate on auth-cookie change and on source restart.
                    # Ordinary analytics cookies never change this generation.
                    identity = sorted(
                        (c.domain, c.path, c.name, c.value)
                        for c in cookies
                        if c.name in target.policy.required_cookie_names
                    )
                    if not identity:
                        identity = sorted(
                            (c.domain, c.path, c.name, c.value) for c in cookies
                        )
                    digest = hmac.digest(
                        self._secret,
                        self._instance
                        + site.encode()
                        + json.dumps(identity, separators=(",", ":")).encode(),
                        hashlib.sha256,
                    )
                    generation = int.from_bytes(digest[:16], "big") + 1
                    return SourceSnapshot(
                        site, generation, serialize_cookies(cookies), headers
                    )
        except SourceUnavailable:
            raise
        except Exception:
            raise SourceUnavailable() from None

    async def open_login(self, site: str) -> None:
        self._site(site)
        try:
            async with asyncio.timeout(35), self._locks[site], self._login_lock:
                existing = self._logins.get(site)
                if existing is not None:
                    try:
                        if existing.pages:
                            await existing.pages[0].bring_to_front()
                            return
                    except Exception:
                        pass
                    await self._close_login(site)
                # Login windows are bounded separately; do not retain a media slot
                # or any task ownership while waiting for the operator.
                if len(self._logins) >= 3:
                    raise SourceUnavailable("login_capacity_reached")
                context = await self._launch(site, visible=True)
                self._logins[site] = context
                self._login_timers[site] = asyncio.create_task(self._expire_login(site))
                try:
                    page = (
                        context.pages[0] if context.pages else await context.new_page()
                    )
                    await page.goto(
                        site_target(site).policy.login_url,
                        wait_until="domcontentloaded",
                        timeout=25_000,
                    )
                    await page.bring_to_front()
                except BaseException as error:
                    await self._close_login(site)
                    if isinstance(error, asyncio.CancelledError):
                        raise
                    raise SourceUnavailable() from None
        except TimeoutError:
            raise SourceUnavailable() from None

    async def finish_login(self, site: str) -> None:
        self._site(site)
        async with self._locks[site]:
            await self._close_login(site)

    async def _expire_login(self, site: str) -> None:
        await asyncio.sleep(15 * 60)
        async with self._locks[site]:
            await self._close_login(site)

    async def _close_login(self, site: str) -> None:
        timer = self._login_timers.pop(site, None)
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()
            await asyncio.gather(timer, return_exceptions=True)
        context = self._logins.pop(site, None)
        if context is not None:
            await context.close()

    async def close(self) -> None:
        try:
            await asyncio.gather(
                *(self._close_login(site) for site in tuple(self._logins)),
                return_exceptions=True,
            )
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
        finally:
            if self._lock_fd is not None:
                os.close(self._lock_fd)
                self._lock_fd = None


def _cookie(value: object) -> Cookie:
    # Kept local to the browser boundary; the rest of the application still uses
    # the bounded Netscape wire format understood by existing extractors.
    from typing import cast

    from playwright._impl._api_structures import Cookie as BrowserCookie

    item = cast(BrowserCookie, value)
    expires = int(item["expires"]) if item["expires"] > 0 else None
    return Cookie(
        0,
        item["name"],
        item["value"],
        None,
        False,
        item["domain"],
        True,
        item["domain"].startswith("."),
        item["path"],
        True,
        item["secure"],
        expires,
        expires is None,
        None,
        None,
        {"HttpOnly": ""} if item["httpOnly"] else {},
    )
