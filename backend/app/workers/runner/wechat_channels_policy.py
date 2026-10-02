"""Fail-closed parsing policy for public WeChat Channels metadata."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator, Mapping
from typing import Any, TypeGuard
from urllib.parse import urlsplit

from app.workers.runner.url_policy import UrlPolicyError, validate_media_url
from app.workers.runner.wechat_channels_response import successful_response_data

_MAX_PROTECTION_NODES = 10_000


class ProtectionScanLimitError(ValueError):
    """The response is too complex to establish absence of protection."""


def feed_info(payload: object) -> Mapping[str, Any] | None:
    data = successful_response_data(payload, "errCode")
    feed = data.get("feedInfo")
    return feed if isinstance(feed, Mapping) and feed else None


def author_info(payload: object) -> Mapping[str, Any]:
    data = successful_response_data(payload, "errCode")
    author = data.get("authorInfo")
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
    if not isinstance(value, str) or any(
        character.isspace() or unicodedata.category(character) in {"Cc", "Cf", "Cs"}
        for character in value
    ):
        return False
    try:
        validated = validate_media_url(value)
    except UrlPolicyError:
        return False
    parsed = urlsplit(validated.value)
    return (
        validated.scheme == "https"
        and parsed.hostname == "finder.video.qq.com"
        and parsed.path.startswith("/251/")
        and parsed.path.endswith("/stodownload")
    )


def has_protection_material(value: object) -> bool:
    # Iterators keep wide responses from being copied into a traversal stack.
    pending: list[Iterator[tuple[object, object]]] = [iter(((None, value),))]
    visited = 0
    while pending:
        try:
            key, item = next(pending[-1])
        except StopIteration:
            pending.pop()
            continue
        visited += 1
        if visited > _MAX_PROTECTION_NODES:
            raise ProtectionScanLimitError("response structure limit exceeded")
        normalized = str(key).replace("_", "").casefold()
        if normalized in {
            "decodekey",
            "drm",
            "hasdrm",
            "encrypted",
            "encryption",
        } and item not in (None, False, 0, "", "0", "false", "none", "null"):
            return True
        if isinstance(item, Mapping):
            pending.append(iter(item.items()))
        elif isinstance(item, list):
            pending.append((None, child) for child in item)
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
        "acodec": None,
        "width": info.get("width"),
        "height": info.get("height"),
    }
