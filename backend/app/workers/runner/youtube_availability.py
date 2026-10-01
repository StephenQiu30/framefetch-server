"""Resolve ambiguous YouTube failures from explicit anonymous Player evidence."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
from app.workers.runner.engine.run_context import RunContext
from app.workers.runner.provider_errors import (
    ProviderFailureContext,
    classify_provider_failure,
)
from app.workers.runner.provider_registry import ProviderRequest

_MAX_PAGE_BYTES = 4 * 1024 * 1024
_PLAYER = re.compile(r"\bytInitialPlayerResponse\s*=\s*")
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")


async def explicit_content_restriction(
    request: ProviderRequest, ctx: RunContext
) -> bool:
    if request.profile.key != "youtube":
        return False
    parsed = urlsplit(request.source_url)
    video_id = (
        parse_qs(parsed.query).get("v", [""])[0]
        if parsed.path == "/watch"
        else parsed.path.rstrip("/").rsplit("/", 1)[-1]
    )
    if _VIDEO_ID.fullmatch(video_id) is None:
        return False
    remaining = min(5.0, (ctx.deadline - datetime.now(UTC)).total_seconds())
    if remaining <= 0:
        return False
    try:
        # Public scope is independent of the logged-in mweb client. Do not send
        # identity material, follow redirects, or persist the page/Player data.
        async with asyncio.timeout(remaining):
            async with httpx.AsyncClient(
                proxy=ctx.egress.proxy_url,
                trust_env=False,
                follow_redirects=False,
                timeout=remaining,
            ) as client:
                async with client.stream(
                    "GET", "https://www.youtube.com/watch", params={"v": video_id}
                ) as response:
                    if response.status_code != 200:
                        return False
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > _MAX_PAGE_BYTES:
                            return False
        page = body.decode("utf-8")
        marker = _PLAYER.search(page)
        if marker is None:
            return False
        player, _ = json.JSONDecoder().raw_decode(page[marker.end() :])
        if not isinstance(player, dict):
            return False
        status = player.get("playabilityStatus")
        if not isinstance(status, dict) or status.get("status") not in {
            "ERROR",
            "UNPLAYABLE",
            "LOGIN_REQUIRED",
        }:
            return False
        reason = status.get("reason")
        if not isinstance(reason, str):
            return False
        failure = classify_provider_failure(
            ProviderFailureContext("youtube", request.source_url, False),
            reason.encode(),
        )
        return failure is not None and failure[0] == "content_unavailable"
    except (httpx.HTTPError, TimeoutError, ValueError):
        # Lack of affirmative evidence must preserve the original diagnosis.
        return False
