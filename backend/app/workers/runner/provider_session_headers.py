"""Encode provider-scoped browser headers inside the private Cookie jar."""

from __future__ import annotations

import base64
import json
from http.cookiejar import Cookie, CookieJar

SESSION_HEADER_COOKIE = "__framefetch_headers"
SESSION_HEADER_URL = "https://session.yuanbao.tencent.com/"
_SESSION_HEADER_DOMAIN = "session.yuanbao.tencent.com"
_ALLOWED_HEADERS = frozenset(
    {
        "x-agentid",
        "x-commit-tag",
        "x-device-id",
        "x-exp-params",
        "x-hy106",
        "x-hy92",
        "x-hy93",
        "x-instance-id",
        "x-language",
        "x-os_version",
        "x-platform",
        "x-source",
        "x-trid-channel",
        "x-web-ch-id",
        "x-web-third-source",
        "x-webdriver",
        "x-webversion",
        "x-ybuitest",
        "user-agent",
    }
)
_MAX_HEADERS = 32
_MAX_HEADER_VALUE_BYTES = 1024


def yuanbao_session_cookie_jar(auth: dict[str, object]) -> CookieJar:
    """Carry the Yuanbao page identity and headers as private Cookie entries."""
    jar = CookieJar()
    for name, key in (("hy_user", "userId"), ("hy_token", "token")):
        value = auth.get(key)
        if isinstance(value, str) and value:
            jar.set_cookie(_cookie(name, value))
    headers = _validated_headers(auth.get("headers"))
    if headers:
        payload = json.dumps(headers, separators=(",", ":")).encode()
        encoded = base64.urlsafe_b64encode(payload).decode()
        jar.set_cookie(
            _cookie(SESSION_HEADER_COOKIE, encoded, domain=_SESSION_HEADER_DOMAIN)
        )
    return jar


def decode_session_headers(value: str) -> dict[str, str]:
    try:
        decoded = base64.b64decode(value, altchars=b"-_", validate=True)
        raw = json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return _validated_headers(raw)


def _validated_headers(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict) or len(raw) > _MAX_HEADERS:
        return {}
    headers: dict[str, str] = {}
    for name, value in raw.items():
        if (
            isinstance(name, str)
            and isinstance(value, str)
            and name.casefold() in _ALLOWED_HEADERS
            and "\r" not in value
            and "\n" not in value
            and len(value.encode()) <= _MAX_HEADER_VALUE_BYTES
        ):
            headers[name] = value
    return headers


def _cookie(name: str, value: str, *, domain: str = ".yuanbao.tencent.com") -> Cookie:
    return Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=True,
        domain_initial_dot=domain.startswith("."),
        path="/",
        path_specified=True,
        secure=True,
        expires=2_147_483_647,
        discard=False,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False,
    )
