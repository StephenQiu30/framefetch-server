from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

import httpx

from app.integrations.article_discovery.parser import parse_article_html
from app.services.source_discoveries.models import ArticleDiscoveryResult
from app.services.source_discoveries.ports import (
    ArticleAccessRestricted,
    ArticleDiscoveryFailure,
)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class WeChatArticleDiscoveryAdapter:
    def __init__(
        self,
        *,
        timeout_seconds: float = 12,
        max_response_bytes: int = 4 * 1024 * 1024,
        max_items: int = 24,
        min_interval_seconds: float = 1,
        proxy_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Callable[[str], Awaitable[tuple[str, ...]]] | None = None,
    ) -> None:
        if (
            timeout_seconds <= 0
            or max_response_bytes < 1024
            or max_items < 1
            or min_interval_seconds < 0.5
        ):
            raise ValueError("article adapter limits must be positive")
        self._timeout = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._max_items = max_items
        self._min_interval = min_interval_seconds
        self._proxy_url = _validated_proxy_url(proxy_url)
        self._last_request_at = 0.0
        self._request_lock = asyncio.Lock()
        self._transport = transport
        self._resolver = resolver or _resolve_addresses

    async def discover(self, url: str) -> ArticleDiscoveryResult:
        if self._proxy_url is None:
            addresses = await self._resolver("mp.weixin.qq.com")
            if not addresses or any(
                not ipaddress.ip_address(item).is_global for item in addresses
            ):
                raise ArticleDiscoveryFailure("article host resolution was rejected")
        async with self._request_lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_request_at = time.monotonic()
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                proxy=self._proxy_url,
                timeout=httpx.Timeout(self._timeout),
                transport=self._transport,
                trust_env=False,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "text/html",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            ) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code in {401, 403, 429}:
                        raise ArticleAccessRestricted("article access is restricted")
                    if response.is_redirect:
                        raise ArticleAccessRestricted("article access is restricted")
                    if response.status_code != 200:
                        raise ArticleDiscoveryFailure("article request failed")
                    content_type = response.headers.get("content-type", "")
                    if "text/html" not in content_type.casefold():
                        raise ArticleDiscoveryFailure("article response is not HTML")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self._max_response_bytes:
                            raise ArticleDiscoveryFailure(
                                "article response exceeded budget"
                            )
                        chunks.append(chunk)
        except ArticleDiscoveryFailure:
            raise
        except (httpx.HTTPError, TimeoutError) as exc:
            raise ArticleDiscoveryFailure("article request failed") from exc
        encoding = response.encoding or "utf-8"
        try:
            payload = b"".join(chunks).decode(encoding, errors="strict")
        except (LookupError, UnicodeDecodeError) as exc:
            raise ArticleDiscoveryFailure("article encoding is invalid") from exc
        return parse_article_html(payload, max_items=self._max_items)


async def _resolve_addresses(host: str) -> tuple[str, ...]:
    loop = asyncio.get_running_loop()
    try:
        rows = await loop.getaddrinfo(
            host,
            443,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise ArticleDiscoveryFailure("article DNS resolution failed") from exc
    return tuple(sorted({row[4][0] for row in rows}))


def _validated_proxy_url(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("article discovery proxy is invalid") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("article discovery proxy must be an HTTP authority")
    return value.rstrip("/")
