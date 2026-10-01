"""Fail-closed parsing policy for public WeChat Channels metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeGuard
from urllib.parse import urlsplit


def feed_info(payload: object) -> Mapping[str, Any] | None:
    if not isinstance(payload, Mapping) or payload.get("errCode") not in (0, "0"):
        return None
    data = payload.get("data")
    feed = data.get("feedInfo") if isinstance(data, Mapping) else None
    return feed if isinstance(feed, Mapping) and feed else None


def author_info(payload: object) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    data = payload.get("data")
    author = data.get("authorInfo") if isinstance(data, Mapping) else None
    return author if isinstance(author, Mapping) else {}


def video_formats(feed: Mapping[str, Any]) -> list[dict[str, Any]]:
    formats: list[dict[str, Any]] = []
    for field, format_id, codec in (
        ("h264VideoInfo", "h264", "h264"),
        ("h265VideoInfo", "h265", "hevc"),
    ):
        info = feed.get(field)
        if not isinstance(info, Mapping):
            continue
        candidate = info.get("videoUrl")
        if allowed_media_url(candidate):
            formats.append(_format(candidate, format_id, codec, info))
    candidate = feed.get("videoUrl")
    if allowed_media_url(candidate) and all(
        item["url"] != candidate for item in formats
    ):
        formats.append(_format(candidate, "source", None, feed))
    return formats


def allowed_media_url(value: object) -> TypeGuard[str]:
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "finder.video.qq.com"
        and parsed.port in (None, 443)
        and parsed.path.startswith("/251/")
        and parsed.path.endswith("/stodownload")
    )


def has_protection_material(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).replace("_", "").casefold()
            if normalized in {
                "decodekey",
                "drm",
                "hasdrm",
                "encrypted",
                "encryption",
            } and item not in (None, False, 0, "", "0", "false", "none", "null"):
                return True
            if has_protection_material(item):
                return True
    elif isinstance(value, list):
        return any(has_protection_material(item) for item in value)
    return False


def _format(
    url: str,
    format_id: str,
    codec: str | None,
    info: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "format_id": format_id,
        "url": url,
        "ext": "mp4",
        "vcodec": codec,
        "acodec": "aac",
        "width": info.get("width"),
        "height": info.get("height"),
    }
