from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.workers.runner.plugins.yt_dlp_plugins.extractor.douyin_share import (
    DouyinNoteIE,
    DouyinOfficialShortIE,
    _allowed_share_url,
    _canonical_note_url,
    _canonical_video_url,
    _correct_download_addr_dimensions,
    _DouyinSharePageIE,
    _is_official_note_url,
    _router_item,
)
from yt_dlp.extractor.tiktok import DouyinIE
from yt_dlp.networking.exceptions import TransportError  # type: ignore[import-untyped]
from yt_dlp.utils import ExtractorError  # type: ignore[import-untyped]


@pytest.fixture(autouse=True)
def offline_visitor_session(monkeypatch: pytest.MonkeyPatch) -> None:
    # Visitor initialization has its own tests; these exercise page parsing.
    for module in ("douyin_share", "douyin_note"):
        monkeypatch.setattr(
            f"app.workers.runner.plugins.yt_dlp_plugins.extractor.{module}"
            ".ensure_visitor_cookies",
            lambda *_args: None,
        )


VIDEO_ID = "7662711608636889201"
URL = f"https://www.douyin.com/video/{VIDEO_ID}"
SHORT_URL = "https://v.douyin.com/Tq0eYJRMYRk/"


def router_payload(video_id: str = VIDEO_ID) -> dict[str, Any]:
    return {
        "loaderData": {
            "video_(id)/page": {
                "videoInfoRes": {
                    "item_list": [
                        {
                            "aweme_id": video_id,
                            "desc": "Public video",
                            "video": {
                                "bit_rate": None,
                                "play_addr": {"url_list": ["https://cdn.test/video"]},
                            },
                        }
                    ]
                }
            }
        }
    }


def test_prefers_matching_public_share_page_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = _DouyinSharePageIE()
    requests: list[tuple[str, str, dict[str, object]]] = []

    def download_webpage(
        url: str,
        video_id: str,
        **kwargs: object,
    ) -> str:
        requests.append((url, video_id, kwargs))
        return "router data"

    monkeypatch.setattr(extractor, "_download_webpage", download_webpage)
    monkeypatch.setattr(
        extractor,
        "_search_json",
        lambda *args, **kwargs: router_payload(),
    )
    monkeypatch.setattr(
        extractor,
        "_parse_aweme_video_app",
        lambda item: {
            "id": item["aweme_id"],
            "title": "Public\nvideo",
            "formats": [{"url": "https://cdn.test/video"}],
        },
    )

    info = extractor._real_extract(URL)

    assert info == {
        "id": VIDEO_ID,
        "title": "Public video",
        "formats": [{"url": "https://cdn.test/video"}],
    }
    assert requests[0][0] == f"https://www.iesdouyin.com/share/video/{VIDEO_ID}/"
    assert requests[0][1] == VIDEO_ID
    assert requests[0][2]["fatal"] is False


def test_official_short_link_resolves_to_canonical_video(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = DouyinOfficialShortIE()
    response = SimpleNamespace(
        url=f"https://www.douyin.com/share/video/{VIDEO_ID}?from=copy"
    )
    requests: list[dict[str, object]] = []

    def request_webpage(*args: object, **kwargs: object) -> object:
        requests.append({"args": args, **kwargs})
        return response

    monkeypatch.setattr(extractor, "_request_webpage", request_webpage)

    result = extractor._real_extract(SHORT_URL)

    assert result["url"] == URL
    assert result["ie_key"] == _DouyinSharePageIE.ie_key()
    assert requests[0]["note"] == "Resolving Douyin official share link"


def test_official_short_link_rejects_non_video_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = DouyinOfficialShortIE()
    monkeypatch.setattr(
        extractor,
        "_request_webpage",
        lambda *_args, **_kwargs: SimpleNamespace(url="https://www.douyin.com/"),
    )

    with pytest.raises(ExtractorError, match="official share link unavailable"):
        extractor._real_extract(SHORT_URL)


def test_official_short_link_rejects_cross_domain_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = DouyinOfficialShortIE()
    monkeypatch.setattr(
        extractor,
        "_request_webpage",
        lambda *_args, **_kwargs: SimpleNamespace(
            url=f"https://example.com/video/{VIDEO_ID}"
        ),
    )

    with pytest.raises(ExtractorError, match="official share link unavailable"):
        extractor._real_extract(SHORT_URL)


def test_official_short_link_identifies_graphic_note_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = DouyinOfficialShortIE()
    monkeypatch.setattr(
        extractor,
        "_request_webpage",
        lambda *_args, **_kwargs: SimpleNamespace(
            url="https://www.iesdouyin.com/share/note/7680102712177097642/"
        ),
    )

    result = extractor._real_extract(SHORT_URL)

    assert result["url"] == (
        "https://www.iesdouyin.com/share/note/7680102712177097642/"
    )
    assert result["ie_key"] == DouyinNoteIE.ie_key()


def test_official_note_redirect_keeps_share_context_for_resolution() -> None:
    assert _canonical_note_url(
        "https://www.iesdouyin.com/share/note/123/?share_sign=opaque&ts=1"
    ) == ("https://www.iesdouyin.com/share/note/123/?share_sign=opaque&ts=1")


def test_douyin_note_extracts_official_slides_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = DouyinNoteIE()
    requests: list[tuple[str, str, dict[str, object]]] = []

    def download_json(
        url: str,
        note_id: str,
        **kwargs: object,
    ) -> dict[str, object]:
        requests.append((url, note_id, kwargs))
        return {
            "aweme_details": [
                {
                    "aweme_id": note_id,
                    "desc": "官方图文\n作品",
                    "images": [
                        {
                            "url_list": [
                                "https://cdn.test/preview.jpg",
                                "https://cdn.test/original.jpg",
                            ],
                            "width": 1080,
                            "height": 1440,
                        },
                        {
                            "url_list": ["https://cdn.test/original.png"],
                            "mime_type": "image/png",
                        },
                    ],
                }
            ]
        }

    monkeypatch.setattr(extractor, "_download_json", download_json)

    info = extractor._real_extract(
        "https://www.iesdouyin.com/share/note/7680102712177097642/"
    )

    assert info["title"] == "官方图文 作品"
    assert info["media_kind"] == "image_gallery"
    assert info["thumbnail"] == "https://cdn.test/original.jpg"
    assert info["assets"] == [
        {
            "url": "https://cdn.test/original.jpg",
            "extension": "jpg",
            "width": 1080,
            "height": 1440,
        },
        {
            "url": "https://cdn.test/original.png",
            "extension": "png",
            "width": None,
            "height": None,
        },
    ]
    assert requests[0][0].endswith("/aweme/slidesinfo/")
    assert requests[0][2]["query"] == {
        "aweme_ids": "7680102712177097642",
        "aweme_type": "68",
        "aid": "1128",
        "request_source": "note",
    }


def test_douyin_note_forwards_official_share_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = DouyinNoteIE()
    calls: list[dict[str, object]] = []

    def download_json(
        _url: str,
        _note_id: str,
        **kwargs: object,
    ) -> dict[str, object]:
        calls.append(kwargs)
        return {
            "aweme_details": [
                {
                    "aweme_id": "123",
                    "images": [{"url_list": ["https://cdn.test/original.jpg"]}],
                }
            ]
        }

    monkeypatch.setattr(extractor, "_download_json", download_json)

    extractor._real_extract(
        "https://www.iesdouyin.com/share/note/123/?share_sign=opaque&ts=1"
    )

    assert calls[0]["query"] == {
        "share_sign": "opaque",
        "ts": "1",
        "aweme_ids": "123",
        "aweme_type": "68",
        "aid": "1128",
        "request_source": "note",
    }


def test_douyin_note_uses_iteminfo_when_slides_api_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = DouyinNoteIE()
    calls: list[str] = []

    def download_json(url: str, *_args: object, **_kwargs: object) -> object:
        calls.append(url)
        if url.endswith("/slidesinfo/"):
            return {"aweme_details": None}
        return {
            "item_list": [
                {
                    "aweme_id": "123",
                    "note_info": {
                        "images": [{"url_list": ["https://cdn.test/iteminfo.webp"]}]
                    },
                }
            ]
        }

    monkeypatch.setattr(extractor, "_download_json", download_json)

    info = extractor._real_extract("https://www.douyin.com/note/123")

    assert info["media_kind"] == "image_gallery"
    assert info["assets"][0]["extension"] == "webp"
    assert calls == [
        "https://www.iesdouyin.com/web/api/v2/aweme/slidesinfo/",
        "https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/",
    ]


def test_douyin_note_reads_current_web_flight_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = DouyinNoteIE()
    flight = "7:" + json.dumps(
        [
            "$",
            "$L9",
            None,
            {
                "awemeId": "123",
                "aweme": {
                    "detail": {
                        "awemeId": "123",
                        "awemeType": 68,
                        "desc": "页面内嵌图文",
                        "images": [
                            {
                                "width": 1280,
                                "height": 720,
                                "urlList": ["https://cdn.test/preview.webp"],
                                "downloadUrlList": ["https://cdn.test/original.webp"],
                            }
                        ],
                    }
                },
            },
        ],
        ensure_ascii=False,
    )
    webpage = f"self.__pace_f.push([1,{json.dumps(flight)}])"
    pages: list[str] = []

    monkeypatch.setattr(
        extractor,
        "_download_json",
        lambda *_args, **_kwargs: {"aweme_details": None},
    )

    def download_webpage(url: str, *_args: object, **_kwargs: object) -> str:
        pages.append(url)
        return webpage if "www.douyin.com/note/123/" in url else ""

    monkeypatch.setattr(extractor, "_download_webpage", download_webpage)
    monkeypatch.setattr(extractor, "_search_json", lambda *_args, **_kwargs: {})

    info = extractor._real_extract("https://www.iesdouyin.com/share/note/123/")

    assert info["media_kind"] == "image_gallery"
    assert info["title"] == "页面内嵌图文"
    assert info["assets"] == [
        {
            "url": "https://cdn.test/original.webp",
            "extension": "webp",
            "width": 1280,
            "height": 720,
        }
    ]
    assert pages == [
        "https://www.iesdouyin.com/share/note/123/",
        "https://www.douyin.com/note/123/",
    ]


def test_douyin_note_accepts_video_media_from_note_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = DouyinNoteIE()
    monkeypatch.setattr(
        extractor,
        "_download_json",
        lambda *_args, **_kwargs: {
            "aweme_details": [
                {
                    "aweme_id": "123",
                    "desc": "官方视频笔记",
                    "video": {"play_addr": {"url_list": ["https://cdn.test/video"]}},
                }
            ]
        },
    )
    monkeypatch.setattr(
        extractor,
        "_parse_aweme_video_app",
        lambda _item: {
            "formats": [{"format_id": "muxed", "url": "https://cdn.test/video"}]
        },
    )

    info = extractor._real_extract("https://www.douyin.com/note/123")

    assert info["id"] == "123"
    assert info["title"] == "官方视频笔记"
    assert info.get("media_kind") is None
    assert info["formats"][0]["url"] == "https://cdn.test/video"


def test_official_short_link_transport_failure_is_temporary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = DouyinOfficialShortIE()

    def fail_transport(*_args: object, **_kwargs: object) -> object:
        raise ExtractorError(
            "Unable to download webpage",
            cause=TransportError("connection reset"),
        )

    monkeypatch.setattr(extractor, "_request_webpage", fail_transport)

    with pytest.raises(
        ExtractorError,
        match="official share link temporarily unavailable",
    ):
        extractor._real_extract(SHORT_URL)


def test_official_short_link_without_redirect_url_is_schema_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = DouyinOfficialShortIE()
    monkeypatch.setattr(
        extractor,
        "_request_webpage",
        lambda *_args, **_kwargs: object(),
    )

    with pytest.raises(
        ExtractorError,
        match="official share link response structure changed",
    ):
        extractor._real_extract(SHORT_URL)


@pytest.mark.parametrize(
    ("url", "expected"),
    (
        (
            f"https://www.douyin.com/video/{VIDEO_ID}/?share=copy",
            URL,
        ),
        (
            f"https://www.douyin.com/share/video/{VIDEO_ID}?share=copy",
            URL,
        ),
        (
            f"https://www.douyin.com/jingxuan?modal_id={VIDEO_ID}",
            URL,
        ),
    ),
)
def test_canonicalizes_official_redirect_video_urls(url: str, expected: str) -> None:
    assert _canonical_video_url(url) == expected


def test_official_redirect_must_use_approved_https_host() -> None:
    assert _allowed_share_url("https://www.douyin.com/video/123")
    assert _allowed_share_url("https://www.iesdouyin.com/share/video/123")
    assert not _allowed_share_url("http://www.douyin.com/video/123")
    assert not _allowed_share_url("https://douyin.com.example/video/123")
    assert not _allowed_share_url("https://example.com/video/123")


def test_official_note_url_requires_a_numeric_note_id() -> None:
    assert _is_official_note_url("https://www.iesdouyin.com/share/note/123/")
    assert _is_official_note_url("https://www.douyin.com/note/123")
    assert not _is_official_note_url("https://www.douyin.com/share/note/abc")
    assert not _is_official_note_url("https://www.douyin.com/share/note/123/more")


def test_corrects_download_format_dimensions_from_video_source() -> None:
    info = _correct_download_addr_dimensions(
        {
            "formats": [
                {"format_id": "download_addr-0", "width": 720, "height": 405},
                {"format_id": "h264_540p-0", "width": 1024, "height": 576},
            ]
        },
        {"video": {"width": 3840, "height": 2160}},
    )

    assert info["formats"] == [
        {"format_id": "download_addr-0", "width": 1280, "height": 720},
        {"format_id": "h264_540p-0", "width": 1024, "height": 576},
    ]


def test_keeps_upstream_download_dimensions_for_portrait_video() -> None:
    info = _correct_download_addr_dimensions(
        {"formats": [{"format_id": "download_addr-0", "width": 720, "height": 1280}]},
        {"video": {"width": 2160, "height": 3840}},
    )

    assert info["formats"] == [
        {"format_id": "download_addr-0", "width": 720, "height": 1280}
    ]


def test_falls_back_to_upstream_extractor_without_share_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = _DouyinSharePageIE()
    monkeypatch.setattr(extractor, "_download_webpage", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        DouyinIE,
        "_real_extract",
        lambda self, url: {"id": VIDEO_ID, "source": "upstream"},
    )

    assert extractor._real_extract(URL) == {"id": VIDEO_ID, "source": "upstream"}


@pytest.mark.parametrize(
    "item",
    [
        {"aweme_id": VIDEO_ID},
        {"aweme_id": VIDEO_ID, "video": {}},
        {"aweme_id": VIDEO_ID, "video": {"play_addr": "invalid"}},
    ],
)
def test_falls_back_when_matching_share_item_is_not_playable(
    monkeypatch: pytest.MonkeyPatch,
    item: dict[str, object],
) -> None:
    extractor = _DouyinSharePageIE()
    payload = {
        "loaderData": {
            "video_(id)/page": {
                "videoInfoRes": {"item_list": [item]},
            }
        }
    }
    monkeypatch.setattr(extractor, "_download_webpage", lambda *args, **kwargs: "data")
    monkeypatch.setattr(extractor, "_search_json", lambda *args, **kwargs: payload)
    monkeypatch.setattr(
        DouyinIE,
        "_real_extract",
        lambda self, url: {"id": VIDEO_ID, "source": "upstream"},
    )

    assert extractor._real_extract(URL) == {"id": VIDEO_ID, "source": "upstream"}


def test_router_item_requires_the_requested_video_identity() -> None:
    payload = router_payload()
    item = _router_item(payload, VIDEO_ID)

    assert item is not None
    assert item["video"]["bit_rate"] == []
    original = payload["loaderData"]["video_(id)/page"]["videoInfoRes"]["item_list"][0]
    assert original["video"]["bit_rate"] is None
    assert _router_item(router_payload("1234567890123456789"), VIDEO_ID) is None
    assert _router_item({"loaderData": []}, VIDEO_ID) is None


def test_plugin_registers_as_the_builtin_douyin_override() -> None:
    assert _DouyinSharePageIE.IE_NAME == "Douyin+share_page"
    assert issubclass(_DouyinSharePageIE, DouyinIE)
    backend_root = Path(__file__).resolve().parents[4]
    result = subprocess.run(
        [
            str(Path(sys.executable).with_name("yt-dlp")),
            "--ignore-config",
            "--verbose",
            "--plugin-dirs",
            str(backend_root / "app/workers/runner"),
            "--simulate",
            "--",
            "file:///disabled",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert "DouyinOfficialShort" in result.stderr
    assert "share_page (DouyinIE)" in result.stderr
    assert (
        str(backend_root / "app/workers/runner/plugins/yt_dlp_plugins") in result.stderr
    )
