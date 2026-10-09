from io import BytesIO
from unittest.mock import patch

import pytest
from app.integrations.article_discovery.native_video import native_videos
from app.workers.runner.plugins.yt_dlp_plugins.extractor.wechat_article import (
    WeChatArticleIE,
)
from tests.unit.integrations.test_article_native_video import article
from yt_dlp.utils import ExtractorError

ARTICLE = "https://mp.weixin.qq.com/s/article_123"


class Response(BytesIO):
    def __init__(self, page, *, url=ARTICLE, content_type="text/html"):
        super().__init__(page.encode())
        self.url = url
        self.headers = {"Content-Type": content_type}


def test_selected_native_work_is_rebound_to_fresh_first_party_metadata():
    page = article()
    video = native_videos(page)[0]
    response = Response(page)
    with patch.object(
        WeChatArticleIE, "_request_webpage", return_value=response
    ) as fetch:
        info = WeChatArticleIE()._real_extract(f"{ARTICLE}#video={video.identity_hash}")
    assert info["id"] == video.video_id and info["duration"] == 12
    assert len(info["formats"]) == 1
    assert info["formats"][0]["url"].startswith("https://mpvideo.qpic.cn/")
    assert info["http_headers"] == {"Referer": ARTICLE}
    assert response.closed
    assert fetch.call_args.args[0] == ARTICLE


@pytest.mark.parametrize(
    "change", ["identity", "redirect", "content-type", "budget", "restricted"]
)
def test_forged_or_restricted_metadata_does_not_return_media(change):
    page = article()
    selection = native_videos(page)[0].identity_hash
    if change == "identity":
        selection = "a" * 64
    if change == "budget":
        page = "x" * (4 * 1024 * 1024 + 1)
    if change == "restricted":
        page = page.replace("is_mp_video_forbid:'0'", "is_mp_video_forbid:'1'")
    response = Response(
        page,
        url="https://other.example/article" if change == "redirect" else ARTICLE,
        content_type="application/json" if change == "content-type" else "text/html",
    )
    with (
        patch.object(WeChatArticleIE, "_request_webpage", return_value=response),
        pytest.raises(ExtractorError, match="content_access_metadata_invalid"),
    ):
        WeChatArticleIE()._real_extract(f"{ARTICLE}#video={selection}")
    assert response.closed
