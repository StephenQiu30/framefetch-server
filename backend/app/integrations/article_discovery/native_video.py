"""Read bounded first-party video literals without executing page JavaScript.

Signed sources are operation-local; discovery only keeps the identity hash.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from yt_dlp.utils import js_to_json  # type: ignore[import-untyped]

from app.services.source_discoveries.ports import ArticleDiscoveryFailure

_PAGE_INFO = re.compile(r"\bvideo_page_infos?\s*:\s*(?=[{\[])")
_JSON_STRING = re.compile(r'"(?:\\.|[^"\\])*"(?:\s*\*\s*1)?')
_VIDEO_ID = re.compile(r"wxv_[A-Za-z0-9_-]{4,128}")


@dataclass(frozen=True, slots=True)
class NativeVideo:
    video_id: str
    duration_ms: int
    formats: tuple[dict[str, object], ...] = field(repr=False)

    @property
    def identity_hash(self) -> str:
        return hashlib.sha256(f"native:{self.video_id}".encode()).hexdigest()


def native_videos(payload: str, *, max_items: int = 24) -> tuple[NativeVideo, ...]:
    if len(payload.encode()) > 4 * 1024 * 1024:
        raise ArticleDiscoveryFailure("article response exceeded budget")
    videos: list[NativeVideo] = []
    seen: set[str] = set()
    for marker in _PAGE_INFO.finditer(payload):
        literal = _object_literal(payload, marker.end())
        try:
            document = _JSON_STRING.sub(_numeric_coercion, js_to_json(literal))
            info = json.loads(document)
        except (ValueError, TypeError, RecursionError) as exc:
            raise ArticleDiscoveryFailure("article video metadata is invalid") from exc
        records = info if isinstance(info, list) else [info]
        for record in records:
            if not isinstance(record, dict):
                raise ArticleDiscoveryFailure("article video metadata is invalid")
        for record in records:
            if not record.get("video_id") and not record.get("mp_video_trans_info"):
                continue
            videos.append(_native_video(record))
            video_id = videos[-1].video_id
            if video_id in seen or len(videos) > max_items:
                raise ArticleDiscoveryFailure("article video identity is ambiguous")
            seen.add(video_id)
    return tuple(videos)


def _native_video(info: dict[str, object]) -> NativeVideo:
    video_id = info.get("video_id")
    if not isinstance(video_id, str) or not _VIDEO_ID.fullmatch(video_id):
        raise ArticleDiscoveryFailure("article video identity is invalid")
    _reject_restrictions(info)
    if (
        type(info.get("is_mp_video")) is not int
        or type(info.get("is_mp_video_delete")) is not int
        or type(info.get("is_mp_video_forbid")) is not int
        or info.get("is_mp_video") != 1
        or info.get("is_mp_video_delete") != 0
        or info.get("is_mp_video_forbid") != 0
    ):
        raise ArticleDiscoveryFailure("article video is unavailable")
    tiers = info.get("mp_video_trans_info")
    if not isinstance(tiers, list) or not 0 < len(tiers) <= 24:
        raise ArticleDiscoveryFailure("article video renditions are unavailable")
    formats: list[dict[str, object]] = []
    duration_ms: int | None = None
    format_ids: set[str] = set()
    for tier in tiers:
        if not isinstance(tier, dict):
            raise ArticleDiscoveryFailure("article video rendition is invalid")
        _reject_restrictions(tier)
        url = html.unescape(str(tier.get("url") or ""))
        url = _validate_media_url(url)
        duration = _positive_integer(tier.get("duration_ms"))
        if duration_ms is not None and abs(duration - duration_ms) > max(
            3000, duration_ms * 0.02
        ):
            raise ArticleDiscoveryFailure("article video duration is ambiguous")
        duration_ms = duration if duration_ms is None else duration_ms
        format_id = str(_positive_integer(tier.get("format_id")))
        if format_id in format_ids:
            raise ArticleDiscoveryFailure("article video rendition is ambiguous")
        format_ids.add(format_id)
        formats.append(
            {
                "format_id": format_id,
                "url": url,
                "ext": "mp4",
                "protocol": "https",
                "width": _positive_integer(tier.get("width")),
                "height": _positive_integer(tier.get("height")),
                "filesize": _positive_integer(tier.get("filesize")),
            }
        )
    assert duration_ms is not None
    return NativeVideo(video_id, duration_ms, tuple(formats))


def _numeric_coercion(match: re.Match[str]) -> str:
    value = match.group()
    if not value.endswith("1"):
        return value
    literal, separator, multiplier = value.rpartition("*")
    if not separator or multiplier.strip() != "1":
        return value
    number = json.loads(literal)
    if not isinstance(number, str) or not re.fullmatch(r"[0-9]+", number):
        raise ValueError("unsupported numeric coercion")
    return str(int(number))


def _object_literal(payload: str, offset: int) -> str:
    stack: list[str] = []
    quote = ""
    escaped = False
    for position in range(offset, min(len(payload), offset + 512 * 1024)):
        char = payload[position]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in {"'", '"'}:
            quote = char
        elif char in "{[":
            stack.append(char)
            if len(stack) > 16:
                break
        elif char in "}]":
            if not stack or stack.pop() != ("{" if char == "}" else "["):
                break
            if not stack:
                return payload[offset : position + 1]
    raise ArticleDiscoveryFailure("article video literal exceeded budget")


def _positive_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ArticleDiscoveryFailure("article video metadata is invalid")
    if not re.fullmatch(r"[0-9]{1,16}", str(value)) or int(value) <= 0:
        raise ArticleDiscoveryFailure("article video metadata is invalid")
    return int(value)


def _validate_media_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        valid = (
            len(value) <= 4096
            and not any(c.isspace() or ord(c) < 32 or c == "\\" for c in value)
            and parsed.scheme in {"http", "https"}
            and parsed.hostname == "mpvideo.qpic.cn"
            and parsed.port in (None, 80 if parsed.scheme == "http" else 443)
            and parsed.username is None
            and parsed.password is None
            and parsed.path.endswith(".mp4")
            and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise ArticleDiscoveryFailure("article video source is invalid")
    # The official bootstrap still emits HTTP sources. Use the same fixed
    # first-party host over TLS; never send a signed source over plaintext.
    return urlunsplit(parsed._replace(scheme="https", netloc="mpvideo.qpic.cn"))


def _reject_restrictions(info: dict[str, object]) -> None:
    for flag in (
        "has_drm",
        "is_encrypted",
        "is_paid",
        "is_preview",
        "preview_only",
        "requires_purchase",
    ):
        if flag in info and info[flag] not in (False, 0, "0"):
            raise ArticleDiscoveryFailure("article video is restricted")
