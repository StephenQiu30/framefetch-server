"""Parse Douyin's own detail response or hydrated share-page state."""

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

RULES = BrowserRules(
    "douyin", ("/aweme/v1/web/aweme/detail/", "/aweme/v1/aweme/detail/")
)
HOME = "https://www.douyin.com/"
STATE = "() => window.__ROUTER_DATA__ || window._SSR_HYDRATED_DATA || null"


def _parse_response(
    payload: Mapping[str, object], expected_id: str | None = None
) -> ResolvedMedia:
    items = [
        node
        for node in objects(dict(payload))
        if node.get("aweme_id") and isinstance(node.get("video"), dict)
    ]
    item = next(
        (
            node
            for node in items
            if expected_id is None or str(node["aweme_id"]) == expected_id
        ),
        None,
    )
    if item is None:
        raise failure(FailureClass.EXTRACTOR_BROKEN, "detail_missing")
    public_item(item)
    status = item.get("status", {})
    if isinstance(status, dict) and (
        status.get("is_delete") or status.get("private_status", 0) not in (0, "0")
    ):
        raise failure(FailureClass.CONTENT_UNAVAILABLE, "restricted_content", "none")
    video = item["video"]
    variants = [
        rate.get("play_addr")
        for rate in video.get("bit_rate", [])
        if isinstance(rate, dict)
    ]
    variants.extend([video.get("play_addr"), video.get("play_addr_h264")])
    formats: list[dict[str, Any]] = []
    for address in variants:
        if not isinstance(address, dict):
            continue
        urls = address.get("url_list", [])
        if not isinstance(urls, list):
            continue
        for url in urls[:1]:
            if isinstance(url, str):
                formats.append(
                    {
                        "format_id": f"browser-{len(formats)}",
                        "url": url,
                        "ext": "mp4",
                        "width": address.get("width") or video.get("width"),
                        "height": address.get("height") or video.get("height"),
                        "vcodec": "h264",
                        "acodec": "aac",
                        "fps": video.get("fps") or 30,
                    }
                )
    cover = video.get("cover", {})
    thumbnails = cover.get("url_list", []) if isinstance(cover, dict) else []
    return media(
        {
            "id": str(item["aweme_id"]),
            "title": item.get("desc") or str(item["aweme_id"]),
            "duration": (video.get("duration") or item.get("duration") or 0) / 1000,
            "extractor_key": "Douyin",
            "formats": formats,
            "thumbnails": [{"url": url} for url in thumbnails],
        },
        "douyin",
    )


def parse_response(
    payload: Mapping[str, object], expected_id: str | None = None
) -> ResolvedMedia:
    try:
        return _parse_response(payload, expected_id)
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        raise failure(FailureClass.EXTRACTOR_BROKEN, "invalid_page_metadata") from None
