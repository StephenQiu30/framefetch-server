"""Bounded first-party page response collection and media normalization."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import fields
from typing import Any
from urllib.parse import urlsplit

from app.services.provider_failures import FailureClass
from app.workers.runner.engine.layers.base import LayerFailure
from app.workers.runner.engine.resolved import ResolvedMedia
from app.workers.runner.entitlements import enforce_media_rights
from app.workers.runner.metadata import normalize_metadata
from playwright.async_api import Page, Response

MAX_RESPONSE_BYTES = 4 * 1024**2


def failure(kind: FailureClass, cause: str, gate: str = "②") -> LayerFailure:
    return LayerFailure(kind, gate, {"kind": "upstream_response", "cause_code": cause})  # type: ignore[arg-type]


def objects(value: object, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 10:
        return []
    result: list[dict[str, Any]] = []
    if isinstance(value, dict):
        result.append(value)
        children = list(value.values())[:100]
    elif isinstance(value, list):
        children = value[:100]
    else:
        return result
    for child in children:
        result.extend(objects(child, depth + 1))
        if len(result) > 2000:
            break
    return result


def public_item(item: Mapping[str, Any]) -> None:
    for node in objects(dict(item)):
        if any(
            node.get(key) not in (None, False, 0, "0")
            for key in (
                "is_private",
                "is_friend_only",
                "is_friends_only",
                "is_member_only",
                "is_charge_content",
                "is_preview",
                "requires_purchase",
                "is_paid",
            )
        ):
            raise failure(
                FailureClass.CONTENT_UNAVAILABLE, "restricted_content", "none"
            )
        if any(
            node.get(key) not in (None, False, 0, "0")
            for key in (
                "has_drm",
                "drm",
                "is_drm",
                "is_encrypt",
                "is_encrypted",
            )
        ):
            raise failure(FailureClass.CONTENT_PROTECTED, "protected_media", "none")
    enforce_media_rights(item, provider_key="browser")


def media(payload: dict[str, Any], platform: str) -> ResolvedMedia:
    enforce_media_rights(payload, provider_key=platform)
    normalized = normalize_metadata(
        payload, max_duration_seconds=86400, max_candidate_streams=64
    )
    return ResolvedMedia(
        **{f.name: getattr(normalized, f.name) for f in fields(normalized)},
        client=f"{platform}:browser",
        handoff="http",
    )


class PageResponses:
    """Only responses issued by this page, never synthetic signed requests."""

    def __init__(self, page: Page, platform: str, patterns: tuple[str, ...]) -> None:
        self.page = page
        self.platform = platform
        self.patterns = patterns
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=8)
        self.tasks: set[asyncio.Task[None]] = set()
        self.media_urls: set[str] = set()

    def start(self) -> None:
        self.page.on("response", self._response)

    def _response(self, response: Response) -> None:
        parsed = urlsplit(response.url)
        if (
            response.status == 200
            and response.headers.get("content-type", "").startswith("video/")
            and len(self.media_urls) < 64
        ):
            self.media_urls.add(response.url)
        host = parsed.hostname or ""
        domains = (
            ("kuaishou.com", "kuaishou.cn", "chenzhongtech.com", "gifshow.com")
            if self.platform == "kuaishou"
            else (f"{self.platform}.com",)
        )
        if not any(host == domain or host.endswith(f".{domain}") for domain in domains):
            return
        if not any(pattern in parsed.path for pattern in self.patterns):
            return
        if len(self.tasks) >= 8 or self.queue.full():
            return
        task = asyncio.create_task(self._read(response))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _read(self, response: Response) -> None:
        try:
            length = response.headers.get("content-length")
            if length and int(length) > MAX_RESPONSE_BYTES:
                return
            body = await response.body()
            if len(body) > MAX_RESPONSE_BYTES:
                return
            import json

            payload = json.loads(body)
            if isinstance(payload, dict) and not self.queue.full():
                self.queue.put_nowait(payload)
        except Exception:
            # A cancelled navigation can invalidate a response. No raw text escapes.
            return

    async def close(self) -> None:
        self.page.remove_listener("response", self._response)
        for task in tuple(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
