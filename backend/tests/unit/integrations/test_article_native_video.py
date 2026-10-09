from __future__ import annotations

import pytest
from app.integrations.article_discovery.native_video import native_videos
from app.integrations.article_discovery.parser import parse_article_html
from app.services.source_discoveries.ports import ArticleDiscoveryFailure


def article(
    *, url: str = "http://mpvideo.qpic.cn/video.f10002.mp4?x=1\\x26amp;t=2"
) -> str:
    return (
        """
    <meta property="og:title" content="视频消息">
    <div id="js_content"></div><script>window.cgiDataNew = {
      video_page_info: {
        video_id:'wxv_native123', is_mp_video:'1' * 1,
        is_mp_video_delete:'0' * 1, is_mp_video_forbid:'0' * 1,
        mp_video_trans_info: [{format_id:'10002' * 1, width:'1280' * 1,
          height:'720' * 1, duration_ms:'12000' * 1, filesize:'1000000',
          url:'"""
        + url
        + """',}]
      }
    };</script>"""
    )


def test_current_video_message_is_discovered_without_an_iframe_or_url_leak():
    page = article()
    native = native_videos(page)[0]
    item = parse_article_html(page).items[0]
    assert item.duration_ms == 12000
    assert item.identity_evidence_hash == native.identity_hash
    assert item.status == "ready" and item.decision_hint == "candidate"
    assert (
        native.formats[0]["url"] == "https://mpvideo.qpic.cn/video.f10002.mp4?x=1&t=2"
    )
    assert "qpic" not in repr(native) and "qpic" not in repr(item)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/a.mp4",
        "https://mpvideo.qpic.cn.evil.example/a.mp4",
        "https://user:secret@mpvideo.qpic.cn/a.mp4",
        "https://mpvideo.qpic.cn:8443/a.mp4",
        "https://mpvideo.qpic.cn/a.m3u8",
        "https://mpvideo.qpic.cn/a.mp4#key",
        "https://mpvideo.qpic.cn/a.mp4?x=has space",
    ],
)
def test_native_video_rejects_non_official_or_ambiguous_sources(url):
    with pytest.raises(ArticleDiscoveryFailure):
        native_videos(article(url=url))


@pytest.mark.parametrize(
    "change",
    [
        ("is_mp_video_delete:'0'", "is_mp_video_delete:'1'"),
        ("is_mp_video_forbid:'0'", "is_mp_video_forbid:'1'"),
        ("duration_ms:'12000'", "duration_ms:'0'"),
        ("video_id:'wxv_native123'", "video_id:'other'"),
        ("width:'1280' * 1", "width:runCode()"),
    ],
)
def test_native_video_does_not_execute_expressions_or_accept_invalid_metadata(change):
    with pytest.raises(ArticleDiscoveryFailure):
        native_videos(article().replace(*change))


def test_duplicate_identity_and_missing_renditions_fail_closed():
    with pytest.raises(ArticleDiscoveryFailure):
        native_videos(article() + article())
    assert native_videos("<script>video_page_info: {}</script>") == ()


def test_native_video_keeps_all_quality_options_without_sorting_by_format_id():
    page = article().replace(
        "url:'http://mpvideo.qpic.cn/video.f10002.mp4?x=1\\x26amp;t=2',}]",
        "url:'https://mpvideo.qpic.cn/a.mp4'},"
        "{format_id:'10104',width:'480',height:'328',duration_ms:'12000',"
        "filesize:'1000',url:'https://mpvideo.qpic.cn/b.mp4'}]",
    )
    video = native_videos(page)[0]
    assert len(video.formats) == 2
    assert video.formats[0]["width"] == 1280
    assert video.formats[1]["width"] == 480


def test_regular_article_video_array_and_empty_video_message_slot():
    page = (
        article()
        .replace("video_page_info: {", "video_page_infos: [{")
        .replace("    };", "    };")
    )
    page = page.replace("      }\n    };", "      }]\n    };")
    page += "<script>video_page_info: {mp_video_trans_info:[],drama_info:{}}</script>"
    assert native_videos(page)[0].duration_ms == 12000


@pytest.mark.parametrize("flag", ["has_drm", "is_encrypted", "is_paid", "is_preview"])
def test_known_restrictions_are_rejected_before_returning_signed_media(flag):
    with pytest.raises(ArticleDiscoveryFailure):
        native_videos(article().replace("video_id:'", f"{flag}:true, video_id:'"))
