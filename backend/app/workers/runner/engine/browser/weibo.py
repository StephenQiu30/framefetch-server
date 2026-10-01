"""Read status responses issued by Weibo's own page; reuse upstream metadata rules."""

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
from yt_dlp.extractor.weibo import WeiboBaseIE  # type: ignore[import-untyped]

RULES = BrowserRules("weibo", ("/ajax/statuses/show", "/ajax/statuses/longtext"))
HOME = "https://weibo.com/"
STATE = "() => ({statuses: window.$render_data || null})"


def parse_response(
    payload: Mapping[str, object], expected_id: str | None = None
) -> ResolvedMedia:
    try:
        item = next(
            (
                node
                for node in objects(dict(payload))
                if isinstance(node.get("page_info"), dict)
                and (node.get("id") or node.get("idstr") or node.get("id_str"))
                and (
                    expected_id is None
                    or expected_id
                    in {
                        str(node.get("id")),
                        str(node.get("idstr")),
                        str(node.get("id_str")),
                        str(node.get("mblogid")),
                    }
                )
            ),
            None,
        )
        if item is None:
            raise failure(FailureClass.EXTRACTOR_BROKEN, "status_missing")
        public_item(item)
        visible = item.get("visible", {})
        if isinstance(visible, dict) and visible.get("type", 0) not in (0, "0"):
            raise failure(
                FailureClass.CONTENT_UNAVAILABLE, "restricted_content", "none"
            )
        # These upstream methods only transform the captured dict; no HTTP calls.
        parsed = WeiboBaseIE()._parse_video_info(item)
        return media(parsed, "weibo")
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        raise failure(FailureClass.EXTRACTOR_BROKEN, "invalid_page_metadata") from None
