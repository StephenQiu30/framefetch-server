"""HTTP admission and browser security policy for the public API."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.api.browser_origin import requires_browser_origin, same_browser_origin
from app.api.errors import error_response, unexpected_error_handler
from app.core.errors import AppError
from app.services.auth.avatars import MAX_AVATAR_UPLOAD_BYTES


class RequestBodyTooLarge(Exception):
    """Raised while streaming a request that exceeds the admission budget."""


async def request_guard(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
    *,
    max_body_bytes: int,
    timeout_seconds: float,
    production: bool,
    connect_origins: tuple[str, ...] = (),
    media_origins: tuple[str, ...] = (),
) -> Response:
    settings = request.app.state.settings
    if request.url.path == "/api/users/me/avatar" and request.method == "PUT":
        max_body_bytes = max(max_body_bytes, MAX_AVATAR_UPLOAD_BYTES)
    if requires_browser_origin(request, settings) and not same_browser_origin(
        request, settings
    ):
        return _guard_error(
            request,
            403,
            "forbidden",
            "The browser request origin is not allowed.",
            production=production,
            connect_origins=connect_origins,
            media_origins=media_origins,
        )
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
            if declared_length < 0:
                raise ValueError
            if declared_length > max_body_bytes:
                return _guard_error(
                    request,
                    413,
                    "request_too_large",
                    "Request body is too large.",
                    production=production,
                    connect_origins=connect_origins,
                    media_origins=media_origins,
                )
        except ValueError:
            return _guard_error(
                request,
                400,
                "invalid_request",
                "The request is invalid.",
                production=production,
                connect_origins=connect_origins,
                media_origins=media_origins,
            )
    try:
        async with asyncio.timeout(timeout_seconds):
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > max_body_bytes:
                    raise RequestBodyTooLarge
            request._body = bytes(body)
            response = await call_next(request)
    except RequestBodyTooLarge:
        return _guard_error(
            request,
            413,
            "request_too_large",
            "Request body is too large.",
            production=production,
            connect_origins=connect_origins,
            media_origins=media_origins,
        )
    except TimeoutError:
        return _guard_error(
            request,
            504,
            "request_timeout",
            "The request exceeded its deadline.",
            production=production,
            connect_origins=connect_origins,
            media_origins=media_origins,
        )
    except Exception as error:
        response = await unexpected_error_handler(request, error)
    _security_headers(
        response,
        production=production,
        connect_origins=connect_origins,
        media_origins=media_origins,
    )
    return response


def _guard_error(
    request: Request,
    status: int,
    code: str,
    detail: str,
    *,
    production: bool,
    connect_origins: tuple[str, ...],
    media_origins: tuple[str, ...],
) -> JSONResponse:
    response = error_response(
        request,
        AppError(
            status=status,
            code=code,
            title="Invalid request" if status < 500 else "Request failed",
            detail=detail,
        ),
    )
    _security_headers(
        response,
        production=production,
        connect_origins=connect_origins,
        media_origins=media_origins,
    )
    return response


def _security_headers(
    response: Response,
    *,
    production: bool,
    connect_origins: tuple[str, ...],
    media_origins: tuple[str, ...],
) -> None:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        _csp(connect_origins=connect_origins, media_origins=media_origins),
    )
    if production:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )


def _csp(*, connect_origins: tuple[str, ...], media_origins: tuple[str, ...]) -> str:
    connect_sources = " ".join(("'self'", *connect_origins))
    media_sources = " ".join(("'self'", *media_origins))
    return (
        "default-src 'self'; script-src 'self' 'unsafe-inline' "
        "https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        # Private thumbnails are fetched with the authenticated HTTP client
        # and rendered from an in-memory object URL after integrity checks.
        "img-src 'self' data: blob: https:; "
        f"connect-src {connect_sources}; media-src {media_sources}; "
        "frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'"
    )
