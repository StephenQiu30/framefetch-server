"""Obtain Douyin's first-party visitor cookies inside the extractor's own jar.

Request first-party pages to initialize the extractor's visitor context.
Successful extraction still depends on the platform response and media checks.
The cookies live only in this yt-dlp process: nothing is persisted or shared.
"""

from __future__ import annotations

from yt_dlp.extractor.common import InfoExtractor  # type: ignore[import-untyped]

_VISITOR_PAGES = ("https://www.iesdouyin.com/", "https://www.douyin.com/")


def ensure_visitor_cookies(ie: InfoExtractor, video_id: str) -> None:
    if "ttwid" in ie._get_cookies("https://www.douyin.com/"):
        return
    for page in _VISITOR_PAGES:
        ie._request_webpage(
            page,
            video_id,
            note="Initializing Douyin visitor session",
            errnote=False,
            fatal=False,
        )
