"""Per-operation page headers from the platform dedicated browser context."""

from __future__ import annotations

import json
from collections.abc import Iterable
from http.cookiejar import Cookie
from typing import TYPE_CHECKING

from app.services.site_sessions import HeaderPlugin, SiteSessionPolicy

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext

# Matches the Runner's WeChat Channels extractor so signatures and requests
# present one client identity.
PAGE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
_PAGE_TIMEOUT_MS = 30_000

_YUANBAO_AUTH = """
async () => {
  if (location.origin !== 'https://yuanbao.tencent.com') return {};
  const auth = {
    userId: localStorage.getItem('yb_user_id') || '',
    token: localStorage.getItem('yb_token') || ''
  };
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


class PageHeadersUnavailable(Exception):
    """The page did not produce a usable identity and header set."""


async def page_headers(
    policy: SiteSessionPolicy, cookies: tuple[Cookie, ...], context: BrowserContext
) -> bytes | None:
    """Use the same persistent origin state as the dedicated login browser."""
    if policy.header_plugin is not HeaderPlugin.YUANBAO:
        return None
    page = await context.new_page()
    try:
        await page.goto(
            policy.login_url, wait_until="domcontentloaded", timeout=_PAGE_TIMEOUT_MS
        )
        await page.wait_for_function("() => !!window.$webApi", timeout=_PAGE_TIMEOUT_MS)
        auth = await page.evaluate(_YUANBAO_AUTH)
        return yuanbao_payload(auth, cookies)
    finally:
        await page.close()


def yuanbao_payload(auth: object, cookies: Iterable[Cookie]) -> bytes:
    """Identity from the page, else from the operator's login Cookies."""
    if not isinstance(auth, dict):
        raise PageHeadersUnavailable("page returned no identity")
    by_name = {cookie.name: cookie.value or "" for cookie in cookies}
    user = auth.get("userId") or by_name.get("hy_user")
    token = auth.get("token") or by_name.get("hy_token")
    headers = auth.get("headers")
    if not (isinstance(user, str) and user and isinstance(token, str) and token):
        raise PageHeadersUnavailable("no Yuanbao login identity")
    if not isinstance(headers, dict) or not headers:
        raise PageHeadersUnavailable("page produced no request headers")
    return json.dumps(
        {"userId": user, "token": token, "headers": headers},
        separators=(",", ":"),
    ).encode()
