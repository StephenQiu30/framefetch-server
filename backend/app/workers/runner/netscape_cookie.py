"""Validation and serialization for bounded Netscape Cookie payloads."""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from http.cookiejar import Cookie

from app.workers.runner.errors import RunnerFailure

MAX_COOKIE_BYTES = 1024**2

_NETSCAPE_HEADERS = (
    b"# Netscape HTTP Cookie File",
    b"# HTTP Cookie File",
)
_CONTROL = frozenset("\t\r\n\x00")


@dataclass(frozen=True, slots=True)
class NetscapeCookieLine:
    line: bytes
    expires: int
    name: str


def parse_cookie_payload(
    payload: bytes,
    allowlist: frozenset[str],
) -> tuple[NetscapeCookieLine, ...]:
    if not 0 < len(payload) <= MAX_COOKIE_BYTES:
        raise RunnerFailure("credential_rejected", status=422)
    lines = payload.splitlines()
    if not lines or not any(lines[0].startswith(item) for item in _NETSCAPE_HEADERS):
        raise RunnerFailure("credential_rejected", status=422)

    normalized_allowlist = frozenset(item.lstrip(".").casefold() for item in allowlist)
    cookies: list[NetscapeCookieLine] = []
    for line in lines[1:]:
        if not line or (line.startswith(b"#") and not line.startswith(b"#HttpOnly_")):
            continue
        fields = line.split(b"\t")
        if len(fields) != 7 or b"\x00" in line:
            raise RunnerFailure("credential_rejected", status=422)
        try:
            domain = fields[0].removeprefix(b"#HttpOnly_").decode("ascii")
            name = fields[5].decode("ascii")
            expires = int(fields[4])
        except (UnicodeDecodeError, ValueError) as exc:
            raise RunnerFailure("credential_rejected", status=422) from exc
        normalized_domain = domain.lstrip(".").casefold()
        if (
            not domain
            or fields[1] not in (b"TRUE", b"FALSE")
            or fields[3] not in (b"TRUE", b"FALSE")
            or not fields[2].startswith(b"/")
            or expires < 0
        ):
            raise RunnerFailure("credential_rejected", status=422)
        if not is_allowed_domain(normalized_domain, normalized_allowlist):
            raise RunnerFailure("credential_rejected", status=422)
        cookies.append(NetscapeCookieLine(line, expires, name))

    if not cookies:
        raise RunnerFailure("credential_rejected", status=422)
    return tuple(cookies)


def live_cookie_payload(
    payload: bytes,
    allowlist: frozenset[str],
    *,
    now: float | None = None,
) -> tuple[bytes, frozenset[str]]:
    cookies = parse_cookie_payload(payload, allowlist)
    current_time = time.time() if now is None else now
    live = [
        cookie
        for cookie in cookies
        if cookie.expires == 0 or cookie.expires > current_time
    ]
    names = frozenset(cookie.name for cookie in live if cookie.line.split(b"\t")[6])
    header = payload.splitlines()[0]
    return b"\n".join([header, *(cookie.line for cookie in live)]) + b"\n", names


def is_allowed_domain(domain: str, allowed_domains: Iterable[str]) -> bool:
    normalized = domain.lstrip(".").casefold()
    return any(
        normalized == allowed.casefold().lstrip(".")
        or normalized.endswith(f".{allowed.casefold().lstrip('.')}")
        for allowed in allowed_domains
    )


def has_safe_cookie_fields(cookie: Cookie) -> bool:
    fields = (cookie.domain, cookie.path, cookie.name, cookie.value or "")
    return all(not (_CONTROL & set(field)) for field in fields)


def serialize_cookies(cookies: Iterable[Cookie]) -> bytes:
    lines = ["# Netscape HTTP Cookie File"]
    for cookie in cookies:
        name, value = cookie.name, cookie.value
        if value is None:
            name, value = "", name
        domain = cookie.domain
        if cookie.has_nonstandard_attr("HttpOnly"):
            domain = f"#HttpOnly_{domain}"
        lines.append(
            "\t".join(
                (
                    domain,
                    "TRUE" if cookie.domain.startswith(".") else "FALSE",
                    cookie.path,
                    "TRUE" if cookie.secure else "FALSE",
                    str(cookie.expires or 0),
                    name,
                    value,
                )
            )
        )
    payload = ("\n".join(lines) + "\n").encode()
    if len(payload) > MAX_COOKIE_BYTES:
        raise OSError("Cookie payload exceeds the bounded session file size")
    return payload
