"""Parse first-party feed and __INITIAL_STATE__ video notes."""

from collections.abc import Mapping
from typing import Any

from app.services.provider_failures import FailureClass
from app.services.provider_types import BrowserRules
from app.workers.runner.engine.browser.intercept import (
    failure,
    media,
    objects,
    public_item,
)
from app.workers.runner.engine.resolved import ResolvedMedia

RULES = BrowserRules("xiaohongshu", ("/api/sns/web/v1/feed", "/api/sns/web/v2/feed"))
HOME = "https://www.xiaohongshu.com/"
STATE = "() => window.__INITIAL_STATE__?.note?.noteDetailMap || null"


def _parse_response(
    payload: Mapping[str, object], expected_id: str | None = None
) -> ResolvedMedia:
    code = payload.get("code")
    if code in (-100, -101, 300012):
        raise failure(FailureClass.CHALLENGE, "request_verification")
    if code in (300031, -510001):
        raise failure(FailureClass.CONTENT_UNAVAILABLE, "note_unavailable", "none")
    items = [
        node
        for node in objects(dict(payload))
        if (node.get("noteId") or node.get("note_id") or node.get("id"))
        and isinstance(node.get("video"), dict)
    ]
    item = next(
        (
            node
            for node in items
            if expected_id is None
            or str(node.get("noteId") or node.get("note_id") or node.get("id"))
            == expected_id
        ),
        None,
    )
    if item is None:
        raise failure(FailureClass.EXTRACTOR_BROKEN, "note_missing")
    public_item(item)
    video = item["video"]
    formats: list[dict[str, Any]] = []
    durations: list[float] = []
    for node in objects(video):
        url = node.get("masterUrl") or node.get("master_url")
        if not isinstance(url, str):
            continue
        milliseconds = node.get("duration")
        if isinstance(milliseconds, (int, float)) and milliseconds > 0:
            durations.append(float(milliseconds) / 1000)
        codec = str(node.get("videoCodec") or node.get("video_codec") or "h264").lower()
        formats.append(
            {
                "format_id": f"browser-{len(formats)}",
                "url": url,
                "ext": "mp4",
                "width": node.get("width"),
                "height": node.get("height"),
                "vcodec": codec,
                "acodec": "aac",
                "fps": node.get("fps") or 30,
            }
        )
    # Only stream.duration is milliseconds. media.duration and capa.duration
    # are rounded seconds, and must never be divided by 1000.
    duration = max(durations, default=0.0)
    if not duration:
        for section in ("capa", "consumer", "media"):
            value = video.get(section, {})
            seconds = value.get("duration") if isinstance(value, dict) else None
            if isinstance(seconds, (int, float)) and seconds > 0:
                duration = float(seconds)
                break
    return media(
        {
            "id": str(item.get("noteId") or item.get("note_id") or item.get("id")),
            "title": item.get("title") or item.get("desc") or "小红书视频",
            "duration": duration,
            "extractor_key": "XiaoHongShu",
            "formats": formats,
        },
        "xiaohongshu",
    )


def parse_response(
    payload: Mapping[str, object], expected_id: str | None = None
) -> ResolvedMedia:
    try:
        return _parse_response(payload, expected_id)
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        raise failure(FailureClass.EXTRACTOR_BROKEN, "invalid_page_metadata") from None
