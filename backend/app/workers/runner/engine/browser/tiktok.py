"""Read TikTok's first-party hydrated item or page-issued detail response."""

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

RULES = BrowserRules("tiktok", ("/api/item/detail/",))
HOME = "https://www.tiktok.com/"
STATE = """() => {
    for (const id of ['__UNIVERSAL_DATA_FOR_REHYDRATION__', 'SIGI_STATE']) {
        const node = document.getElementById(id);
        if (node && node.textContent) {
            try { return JSON.parse(node.textContent); } catch (_) {}
        }
    }
    return null;
}"""


def parse_response(
    payload: Mapping[str, object], expected_id: str | None = None
) -> ResolvedMedia:
    try:
        for node in objects(dict(payload)):
            if node.get("statusCode") in (10204, 10216):
                raise failure(
                    FailureClass.CONTENT_UNAVAILABLE, "video_unavailable", "none"
                )
        item = next(
            (
                node
                for node in objects(dict(payload))
                if isinstance(node.get("video"), dict)
                and node.get("id")
                and (expected_id is None or str(node["id"]) == expected_id)
            ),
            None,
        )
        if item is None:
            raise failure(FailureClass.EXTRACTOR_BROKEN, "detail_missing")
        public_item(item)
        author = item.get("author", {})
        if (
            item.get("secret")
            or item.get("privateItem") is not False
            or not isinstance(author, dict)
            or author.get("privateAccount") is not False
        ):
            raise failure(
                FailureClass.CONTENT_UNAVAILABLE, "restricted_content", "none"
            )
        video = item["video"]
        variants = [video.get("playAddr")]
        variants.extend(
            rate.get("PlayAddr")
            for rate in video.get("bitrateInfo", [])
            if isinstance(rate, dict)
        )
        formats: list[dict[str, Any]] = []
        urls: set[str] = set()
        for address in variants:
            value = (
                address
                if isinstance(address, str)
                else (
                    address.get("UrlList", [None])[0]
                    if isinstance(address, dict)
                    else None
                )
            )
            if not isinstance(value, str) or value in urls:
                continue
            urls.add(value)
            formats.append(
                {
                    "format_id": f"browser-{len(formats)}",
                    "url": value,
                    "ext": "mp4",
                    "width": video.get("width"),
                    "height": video.get("height"),
                    "vcodec": "h264",
                    "acodec": "aac",
                    "fps": video.get("fps") or 30,
                }
            )
        return media(
            {
                "id": str(item["id"]),
                "title": item.get("desc") or str(item["id"]),
                "duration": video.get("duration"),
                "extractor_key": "TikTok",
                "formats": formats,
            },
            "tiktok",
        )
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError, IndexError):
        raise failure(FailureClass.EXTRACTOR_BROKEN, "invalid_page_metadata") from None
