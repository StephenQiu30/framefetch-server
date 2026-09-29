"""Per-operation page headers from the current Chrome platform tab."""

from __future__ import annotations

import json
from collections.abc import Iterable
from http.cookiejar import Cookie


class PageHeadersUnavailable(Exception):
    """The page did not produce a usable identity and header set."""


def yuanbao_payload(auth: object, cookies: Iterable[Cookie]) -> bytes:
    """Identity from the page, else from the operator's login Cookies."""
    if not isinstance(auth, dict):
        raise PageHeadersUnavailable("page returned no identity")
    by_name = {cookie.name: cookie.value or "" for cookie in cookies}
    user = auth.get("userId") or by_name.get("hy_user")
    token = auth.get("token") or by_name.get("hy_token")
    if user != by_name.get("hy_user") or token != by_name.get("hy_token"):
        raise PageHeadersUnavailable("page identity differs from current cookies")
    headers = auth.get("headers")
    if not (isinstance(user, str) and user and isinstance(token, str) and token):
        raise PageHeadersUnavailable("no Yuanbao login identity")
    if not isinstance(headers, dict) or not headers:
        raise PageHeadersUnavailable("page produced no request headers")
    return json.dumps(
        {"userId": user, "token": token, "headers": headers},
        separators=(",", ":"),
    ).encode()
