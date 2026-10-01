"""First-party mobile share state and desktop visionVideoDetail responses."""

from collections.abc import Mapping

from app.services.provider_failures import FailureClass
from app.services.provider_types import BrowserRules
from app.workers.runner.engine.browser.intercept import (
    failure,
    media,
    objects,
    public_item,
)
from app.workers.runner.engine.resolved import ResolvedMedia
from app.workers.runner.plugins.yt_dlp_plugins.extractor.kuaishou_public import (
    _milliseconds,
    _state_photo,
    _video_formats,
)

RULES = BrowserRules("kuaishou", ("/graphql", "/rest/v/photo/info"))
HOME = "https://www.kuaishou.com/"
STATE = "() => window.INIT_STATE || window.__APOLLO_STATE__ || null"


def parse_response(
    payload: Mapping[str, object], expected_id: str | None = None
) -> ResolvedMedia:
    try:
        photo = _state_photo(dict(payload), expected_id) if expected_id else None
        if photo is None:
            photo = next(
                (
                    node
                    for node in objects(dict(payload))
                    if (node.get("id") or node.get("photoId"))
                    and node.get("photoUrl")
                    and (
                        expected_id is None
                        or str(node.get("id") or node.get("photoId")) == expected_id
                    )
                ),
                None,
            )
        if photo is None:
            raise failure(FailureClass.EXTRACTOR_BROKEN, "photo_missing")
        public_item(photo)
        if photo.get("photoType") not in (None, "VIDEO"):
            raise failure(FailureClass.CONTENT_UNAVAILABLE, "not_video", "none")
        formats = _video_formats(photo)
        if not formats and isinstance(photo.get("photoUrl"), str):
            formats = [
                {
                    "format_id": "browser-source",
                    "url": photo["photoUrl"],
                    "ext": "mp4",
                    "width": photo.get("width"),
                    "height": photo.get("height"),
                    "vcodec": "h264",
                    "acodec": "aac",
                    "fps": 30,
                }
            ]
        return media(
            {
                "id": expected_id or str(photo.get("id") or photo.get("photoId")),
                "title": " ".join(str(photo.get("caption") or "快手视频").split()),
                "extractor_key": "KuaishouPublic",
                "duration": _milliseconds(
                    photo.get("duration") or photo.get("durationMs")
                ),
                "formats": formats,
            },
            "kuaishou",
        )
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        raise failure(FailureClass.EXTRACTOR_BROKEN, "invalid_page_metadata") from None
