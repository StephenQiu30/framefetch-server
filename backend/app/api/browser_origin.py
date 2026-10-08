"""Exact browser source validation, including trusted frontend proxy hops."""

from ipaddress import ip_address, ip_network
from urllib.parse import urlsplit

from starlette.requests import HTTPConnection, Request

from app.core.config import Settings


def same_browser_origin(connection: HTTPConnection, settings: Settings) -> bool:
    origin = connection.headers.get("origin")
    referer = connection.headers.get("referer")
    source = _origin(
        origin if origin is not None else referer, allow_path=origin is None
    )
    if source is None:
        return False
    host = connection.headers.get("host", "")
    scheme = connection.scope.get("scheme", "http")
    scheme = {"ws": "http", "wss": "https"}.get(scheme, scheme)
    if _trusted_peer(connection, settings):
        host = connection.headers.get("x-forwarded-host", host)
        scheme = connection.headers.get("x-forwarded-proto", scheme)
    target = _origin(f"{scheme}://{host}", allow_path=False)
    return target is not None and source == target


def requires_browser_origin(request: Request, settings: Settings) -> bool:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return False
    # Login CSRF also matters before there is any cookie. Native routes never
    # consume ambient browser identity and have their own Bearer/body contract.
    if request.url.path.startswith("/api/auth/"):
        return True
    return (
        request.url.path.startswith("/api/")
        and not request.url.path.startswith("/api/app/")
        and "authorization" not in request.headers
        and settings.auth_web_cookie_name in request.cookies
    )


def _trusted_peer(connection: HTTPConnection, settings: Settings) -> bool:
    if connection.client is None:
        return False
    try:
        address = ip_address(connection.client.host)
    except ValueError:
        return False
    return address in settings.trusted_web_proxy_ips or any(
        address in ip_network(cidr) for cidr in settings.trusted_proxy_cidrs
    )


def _origin(value: str | None, *, allow_path: bool) -> tuple[str, str, int] | None:
    if not value or any(c in value for c in "\r\n\t ,\\"):
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or (
                not allow_path
                and (parsed.path not in {"", "/"} or parsed.query or parsed.fragment)
            )
        ):
            return None
        port = (
            parsed.port
            if parsed.port is not None
            else (443 if parsed.scheme == "https" else 80)
        )
        return parsed.scheme, parsed.hostname.casefold(), port
    except ValueError:
        return None
