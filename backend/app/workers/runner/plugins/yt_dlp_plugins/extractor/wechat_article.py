"""Resolve one explicitly selected public WeChat article video."""

from __future__ import annotations

from contextlib import closing
from typing import Any

from app.integrations.article_discovery.native_video import native_videos
from app.integrations.article_discovery.parser import parse_article_html
from app.services.source_discoveries.ports import ArticleDiscoveryFailure
from app.services.source_discoveries.url_admission import (
    canonicalize_article_url,
    selected_article_source,
)
from yt_dlp.extractor.common import InfoExtractor  # type: ignore[import-untyped]

from ._content_access import reject

_MAX_PAGE_BYTES = 4 * 1024 * 1024


class WeChatArticleIE(InfoExtractor):  # type: ignore[misc]
    IE_NAME = "wechat:article"
    _VALID_URL = (
        r"https://mp\.weixin\.qq\.com/s(?:/[^?#]+|\?[^#]+)#video=(?P<id>[0-9a-f]{64})$"
    )

    def _real_extract(self, url: str) -> dict[str, Any]:
        try:
            article, selection = selected_article_source(url)
            with closing(self._request_webpage(article, selection)) as response:
                if canonicalize_article_url(response.url) != article:
                    reject("content_access_metadata_invalid")
                if (
                    "text/html"
                    not in response.headers.get("Content-Type", "").casefold()
                ):
                    reject("content_access_metadata_invalid")
                page_bytes = response.read(_MAX_PAGE_BYTES + 1)
                if len(page_bytes) > _MAX_PAGE_BYTES:
                    reject("content_access_metadata_invalid")
            page = page_bytes.decode("utf-8")
            discovery = parse_article_html(page)
            matches = [v for v in native_videos(page) if v.identity_hash == selection]
        except (ArticleDiscoveryFailure, ValueError):
            reject("content_access_metadata_invalid")
        if len(matches) != 1:
            reject("content_access_metadata_invalid")
        video = matches[0]
        return {
            "id": video.video_id,
            "title": discovery.title,
            "duration": video.duration_ms / 1000,
            "availability": "public",
            "_framefetch_full_stream": True,
            "formats": [dict(item) for item in video.formats],
            "http_headers": {"Referer": article},
        }
