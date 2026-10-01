"""Observe the official player UPS response; never synthesize ccode/signatures."""

from collections.abc import Mapping
from typing import Any
from urllib.parse import urljoin

import httpx
from app.services.provider_failures import FailureClass
from app.services.provider_types import BrowserRules
from app.workers.runner.engine.browser.intercept import failure
from app.workers.runner.engine.resolved import ResolvedMedia
from app.workers.runner.engine.run_context import RunContext
from app.workers.runner.plugins.yt_dlp_plugins.extractor.personal_video import (
    full_youku_streams,
    positive_duration,
)
from app.workers.runner.utilities import safe_media_url
from yt_dlp.utils import ExtractorError  # type: ignore[import-untyped]

RULES = BrowserRules("youku", ("/ups/get.json",))
HOME = "https://www.youku.com/"
STATE = "() => null"
MAX_MANIFEST_BYTES = 2 * 1024**2


def parse_response(
    payload: Mapping[str, object], expected_id: str | None = None
) -> ResolvedMedia:
    # Transport provenance is attached only by the exact first-party collector.
    requested = payload.get("_framefetch_requested_id")
    if not expected_id or requested != expected_id:
        raise failure(FailureClass.EXTRACTOR_BROKEN, "work_identity_mismatch")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise failure(FailureClass.EXTRACTOR_BROKEN, "ups_data_missing")
    error = data.get("error")
    if isinstance(error, dict) and error:
        note = str(error.get("note", ""))
        if any(
            word in note for word in ("私密", "删除", "不存在", "版权", "地区", "密码")
        ):
            raise failure(FailureClass.CONTENT_UNAVAILABLE, "video_unavailable", "none")
        if "drm" in note.casefold() or "加密" in note:
            raise failure(FailureClass.CONTENT_PROTECTED, "protected_media", "none")
        raise failure(FailureClass.CHALLENGE, "ups_client_rejected")
    try:
        streams = full_youku_streams(data)
        video = data["video"]
        duration = positive_duration(video.get("seconds"))
    except ExtractorError:
        raise failure(
            FailureClass.CONTENT_PROTECTED, "full_media_unproven", "none"
        ) from None
    formats: list[dict[str, Any]] = []
    for stream in streams[:8]:
        # No decryption, including non-DRM AES media encryption.
        # UPS "default" is not a clear assertion; manifest/probe checks follow.
        if stream.get("drm_type") not in (None, False, 0, "0", "", "none", "default"):
            continue
        if any(
            stream.get(key) not in (None, False, 0, "0", "", "none")
            for key in ("drm", "has_drm", "encrypt_type", "is_encrypted")
        ):
            continue
        url = stream.get("m3u8_url")
        if isinstance(url, str):
            formats.append(
                {
                    "format_id": f"browser-{len(formats)}",
                    "url": safe_media_url(url),
                    "ext": "mp4",
                    "protocol": "m3u8_native",
                    "width": stream.get("width"),
                    "height": stream.get("height"),
                }
            )
    if not formats:
        raise failure(FailureClass.CONTENT_PROTECTED, "clear_media_missing", "none")
    # Codec candidates are established by the bounded clear-segment probe in
    # BrowserLayer. UPS metadata alone does not justify guessing H.264/AAC.
    return ResolvedMedia(
        provider_media_id=expected_id,
        title=str(video.get("title") or expected_id),
        duration_seconds=duration,
        extractor_key="Youku",
        streams=(),
        client="youku:browser",
        download_info={
            "id": expected_id,
            "title": video.get("title") or expected_id,
            "duration": duration,
            "formats": formats,
            "extractor_key": "Youku",
            "_framefetch_full_stream": True,
        },
    )


def clear_manifest(text: str, base_url: str, duration: float) -> tuple[str, str]:
    """Validate an entire media playlist before ffprobe/FFmpeg can see it."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if any(line.startswith(("#EXT-X-KEY:", "#EXT-X-SESSION-KEY:")) for line in lines):
        raise failure(FailureClass.CONTENT_PROTECTED, "encrypted_playlist", "none")
    if not lines or lines[0] != "#EXTM3U" or "#EXT-X-ENDLIST" not in lines:
        raise failure(FailureClass.CONTENT_PROTECTED, "full_playlist_unproven", "none")
    # Master/byte-range/fMP4 playlists require different completeness/probe rules.
    # Keep this adapter limited to complete segment playlists observed by UPS.
    if any(
        line.startswith(("#EXT-X-STREAM-INF", "#EXT-X-MAP", "#EXT-X-BYTERANGE"))
        for line in lines
    ):
        raise failure(FailureClass.FORMAT_UNAVAILABLE, "playlist_type_unsupported")
    total = 0.0
    segments: list[str] = []
    normalized: list[str] = []
    pending_segment = False
    try:
        for line in lines:
            if line.startswith("#EXTINF:"):
                if pending_segment:
                    raise ValueError("segment missing")
                pending_segment = True
                total += positive_duration(line.partition(":")[2].partition(",")[0])
            if not line.startswith("#"):
                if not pending_segment:
                    raise ValueError("segment duration missing")
                pending_segment = False
                line = safe_media_url(urljoin(base_url, line))
                segments.append(line)
            normalized.append(line)
    except (ExtractorError, ValueError):
        raise failure(
            FailureClass.CONTENT_PROTECTED, "invalid_playlist", "none"
        ) from None
    if (
        pending_segment
        or not segments
        or abs(total - duration) > max(3, duration * 0.02)
    ):
        raise failure(FailureClass.CONTENT_PROTECTED, "preview_playlist", "none")
    return "\n".join(normalized) + "\n", segments[0]


async def prepare_manifests(resolved: ResolvedMedia, ctx: RunContext) -> None:
    try:
        await _prepare_manifests(resolved, ctx)
    except httpx.HTTPError:
        raise failure(FailureClass.NETWORK_BLOCKED, "manifest_network_failed") from None


async def _prepare_manifests(resolved: ResolvedMedia, ctx: RunContext) -> None:
    """Bounded same-egress reads; no keys, redirects or account forwarding."""
    async with httpx.AsyncClient(
        proxy=ctx.egress.proxy_url,
        trust_env=False,
        follow_redirects=False,
        timeout=10,
        headers={"User-Agent": ctx.user_agent, "Referer": ctx.referer},
    ) as client:
        for candidate in resolved.download_info["formats"]:
            url = safe_media_url(candidate["url"])
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise failure(FailureClass.CHALLENGE, "manifest_request_rejected")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_MANIFEST_BYTES:
                        raise failure(
                            FailureClass.FORMAT_UNAVAILABLE, "manifest_size_limit"
                        )
            try:
                text = body.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise failure(
                    FailureClass.EXTRACTOR_BROKEN, "manifest_encoding"
                ) from None
            playlist, probe = clear_manifest(
                text, url, float(resolved.duration_seconds)
            )
            candidate["hls_media_playlist_data"] = playlist
            candidate["_framefetch_probe_url"] = probe
