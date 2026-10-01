from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest
from app.services.provider_types import (
    ProviderKey,
)
from app.workers.runner.entitlements import enforce_media_rights
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.plugins.yt_dlp_plugins.extractor.personal_video import (
    _VQQPersonalIE,
    _YoukuPersonalIE,
    full_youku_streams,
    positive_duration,
)
from yt_dlp import YoutubeDL
from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError


def youku_data() -> dict:
    return {
        "video": {"seconds": 1800, "title": "Synthetic full episode"},
        "stream": [
            {
                "stream_type": "mp4hd",
                "milliseconds_video": 1800000,
                "segs": [{"cdn_url": "https://media.example/full.ts"}],
            }
        ],
    }


def test_youku_incomplete_quality_is_removed_but_full_quality_remains() -> None:
    data = youku_data()
    complete = copy.deepcopy(data["stream"][0])
    data["stream"].extend(
        [
            {"segs": [{"cdn_url": "https://media.example/preview.ts"}, {}]},
            {
                "segs": [{"cdn_url": "https://media.example/preview.ts"}],
                "milliseconds_video": 60000,
            },
            {"channel_type": "tail"},
        ]
    )
    assert full_youku_streams(data) == [complete]


@pytest.mark.parametrize("value", [None, True, 0, -1, "nan", "inf", [], {}])
def test_invalid_duration_cannot_become_completeness_evidence(value) -> None:
    with pytest.raises(ExtractorError, match="content_access_metadata_invalid"):
        positive_duration(value)


@pytest.mark.parametrize(
    "stream,reason",
    [
        ({"segs": [{}]}, "content_preview_only"),
        ({"segs": []}, "content_access_metadata_invalid"),
        ({"segs": [None]}, "content_access_metadata_invalid"),
        ({}, "content_access_metadata_invalid"),
    ],
)
def test_youku_rejects_partial_or_unrecognized_original_segments(
    stream, reason
) -> None:
    data = youku_data()
    data["stream"] = [stream]
    with pytest.raises(ExtractorError, match=reason):
        full_youku_streams(data)


def test_youku_raw_api_guard_runs_before_upstream_normalizes(monkeypatch) -> None:
    extractor = _YoukuPersonalIE(YoutubeDL({"quiet": True}))
    data = youku_data()
    data["stream"][0]["segs"].append({})
    monkeypatch.setattr(InfoExtractor, "_download_json", lambda *a, **k: {"data": data})
    with pytest.raises(ExtractorError, match="content_preview_only"):
        extractor._download_json("https://ups.youku.com/ups/get.json", "fixture")


def test_youku_manifest_drm_is_removed_without_changing_source_duration(
    monkeypatch,
) -> None:
    extractor = _YoukuPersonalIE(YoutubeDL({"quiet": True}))
    original = {
        "id": "fixture",
        "duration": 1800,
        "formats": [{"url": "https://media.example/a.m3u8", "format_id": "hd"}],
    }
    monkeypatch.setattr(
        _YoukuPersonalIE.__bases__[0],
        "_real_extract",
        lambda *a: copy.deepcopy(original),
    )
    monkeypatch.setattr(
        extractor,
        "_extract_m3u8_formats",
        lambda *a, **k: [
            {"url": "https://media.example/clear.m3u8", "has_drm": False},
            {"url": "https://media.example/drm.m3u8", "has_drm": True},
        ],
    )
    result = extractor._real_extract("https://v.youku.com/v_show/id_fixture.html")
    assert result["duration"] == 1800
    assert result["_framefetch_full_stream"] is True
    assert len(result["formats"]) == 1
    monkeypatch.setattr(
        extractor, "_extract_m3u8_formats", lambda *a, **k: [{"has_drm": True}]
    )
    with pytest.raises(ExtractorError, match="drm_protected"):
        extractor._real_extract("https://v.youku.com/v_show/id_fixture.html")


@pytest.mark.parametrize(
    "duration,vid,reason",
    [
        (60, "fixture", "content_preview_only"),
        (1800, "another", "content_access_metadata_invalid"),
        (None, "fixture", "content_access_metadata_invalid"),
    ],
)
def test_tencent_rejects_preview_and_wrong_asset_before_manifest(
    monkeypatch, duration, vid, reason
) -> None:
    extractor = _VQQPersonalIE(YoutubeDL({"quiet": True}))
    extractor._full_duration = 1800

    def unexpected(*a, **k):
        pytest.fail("manifest accessed before content validation")

    monkeypatch.setattr(
        _VQQPersonalIE.__bases__[0], "_extract_video_formats_and_subtitles", unexpected
    )
    with pytest.raises(ExtractorError, match=reason):
        extractor._extract_video_formats_and_subtitles(
            {"vl": {"vi": [{"vid": vid, "td": duration}]}}, "fixture"
        )


def test_tencent_page_duration_is_bound_to_requested_asset(monkeypatch) -> None:
    extractor = _VQQPersonalIE(YoutubeDL({"quiet": True}))
    extractor._source_url = "https://v.qq.com/x/cover/series/fixture.html"
    config = {
        "vinfoConfig": {
            "playerVersion": "1.74.0",
            "adVersion": "4.4.4",
            "vinfoProtoVer": "7",
            "adProtoVer": "2026080601",
            "vinfoProxyDomain": "vd6.l.qq.com",
        }
    }
    page = "<script>window.__STARTUP_CONFIG__=" + json.dumps(config) + "</script>"
    data = {
        "videoInfo": {"vid": "fixture", "duration": 1800},
        "playInfo": {"vid": "fixture", "cid": "series"},
        "proxyhttp": {"enc": 1, "vinfo": "uninterpreted envelope"},
    }
    calls = []

    def fetch(url, vid, *args, **kwargs):
        calls.append((url, kwargs))
        return {"ret": 0, "data": data}

    monkeypatch.setattr(extractor, "_download_json", fetch)
    result = extractor._get_webpage_metadata(page, "fixture")
    assert extractor._full_duration == 1800
    assert "proxyhttp" not in result["global"]
    assert calls[0][0] == "https://vd6.l.qq.com/vinfo_proxy"
    sent = json.loads(calls[0][1]["data"])
    assert sent["vid"] == "fixture"
    assert sent["cid"] == "series"
    data["videoInfo"]["vid"] = "another"
    with pytest.raises(ExtractorError, match="content_access_metadata_invalid"):
        extractor._get_webpage_metadata(page, "fixture")
    with pytest.raises(ExtractorError, match="content_access_metadata_invalid"):
        extractor._get_webpage_metadata(
            page.replace("vd6.l.qq.com", "internal.invalid"), "fixture"
        )
    assert len(calls) == 2


def test_tencent_login_token_is_scoped_to_exact_api_and_never_mutates_query(
    monkeypatch,
) -> None:
    extractor = _VQQPersonalIE(YoutubeDL({"quiet": True}))
    monkeypatch.setattr(
        extractor,
        "_get_cookies",
        lambda url: {
            "v_vuserid": SimpleNamespace(value="synthetic-user"),
            "v_vusession": SimpleNamespace(value="synthetic-session"),
            "unrelated": SimpleNamespace(value="must-not-send"),
        },
    )
    calls = []
    monkeypatch.setattr(
        InfoExtractor, "_download_webpage", lambda *a, **kw: calls.append(kw) or ""
    )
    query = {"vid": "fixture"}
    extractor._download_webpage(extractor._API_URL, "fixture", query=query)
    assert json.loads(calls[0]["query"]["logintoken"]) == {
        "vuserid": "synthetic-user",
        "vusession": "synthetic-session",
    }
    assert query == {"vid": "fixture"}
    extractor._download_webpage("https://media.example/a.m3u8", "fixture")
    assert "query" not in calls[1]


@pytest.mark.parametrize("names", [(), ("v_vuserid",), ("v_vusession",)])
def test_tencent_missing_session_never_makes_anonymous_api_request(
    monkeypatch, names
) -> None:
    extractor = _VQQPersonalIE(YoutubeDL({"quiet": True}))
    monkeypatch.setattr(
        extractor,
        "_get_cookies",
        lambda url: {name: SimpleNamespace(value="synthetic") for name in names},
    )
    calls = []
    monkeypatch.setattr(
        InfoExtractor, "_download_webpage", lambda *a, **kw: calls.append(kw)
    )
    with pytest.raises(ExtractorError, match="login_required"):
        extractor._download_webpage(extractor._API_URL, "fixture")
    assert calls == []


@pytest.mark.parametrize("provider", [ProviderKey.YOUKU, ProviderKey.QQVIDEO])
def test_anonymous_rejects_personal_membership_markers(
    provider,
) -> None:
    with pytest.raises(RunnerFailure) as caught:
        enforce_media_rights({"is_premium": True}, provider_key=provider)
    assert caught.value.code == "content_unavailable"
    with pytest.raises(RunnerFailure) as caught:
        enforce_media_rights(
            {"availability": "premium_only", "_framefetch_full_stream": True},
            provider_key=provider,
        )
    assert caught.value.code == "content_unavailable"
    data = {"_framefetch_full_stream": True}
    for flags in (
        {"is_preview": True},
        {"has_drm": True},
        {"requires_purchase": True},
        {"is_private": True},
    ):
        with pytest.raises(RunnerFailure):
            enforce_media_rights({**data, **flags}, provider_key=provider)
    with pytest.raises(RunnerFailure):
        enforce_media_rights(
            {"is_premium": True, **data},
            provider_key=provider,
        )


@pytest.mark.parametrize("provider", ["youku", "qqvideo"])
@pytest.mark.parametrize(
    "reason",
    [
        "content_preview_only",
        "content_access_metadata_invalid",
        "drm_protected",
        "login_required",
    ],
)
def test_personal_plugin_errors_keep_stable_public_classification(
    provider, reason
) -> None:
    from app.workers.runner.provider_errors import (
        ProviderFailureContext,
        classify_provider_failure,
    )

    context = ProviderFailureContext(provider, "https://example.com/fixture", True)
    assert classify_provider_failure(
        context, f"ERROR: FrameFetch {reason}".encode()
    ) == (
        "content_protected" if reason != "login_required" else "login_required",
        422,
    )


def test_empty_youku_manifest_is_unknown_instead_of_falsely_reported_as_drm(
    monkeypatch,
) -> None:
    extractor = _YoukuPersonalIE(YoutubeDL({"quiet": True}))
    monkeypatch.setattr(
        _YoukuPersonalIE.__bases__[0],
        "_real_extract",
        lambda *a: {
            "id": "fixture",
            "duration": 1800,
            "formats": [{"url": "https://media.example/empty.m3u8", "format_id": "hd"}],
        },
    )
    monkeypatch.setattr(extractor, "_extract_m3u8_formats", lambda *a, **k: [])
    with pytest.raises(ExtractorError, match="content_access_metadata_invalid"):
        extractor._real_extract("https://v.youku.com/v_show/id_fixture.html")


def test_tencent_clear_api_flag_cannot_erase_manifest_drm(monkeypatch) -> None:
    extractor = _VQQPersonalIE(YoutubeDL({"quiet": True}))
    extractor._full_duration = 1800
    monkeypatch.setattr(
        InfoExtractor,
        "_extract_m3u8_formats_and_subtitles",
        lambda *a, **k: (
            [{"url": "https://media.example/encrypted.m3u8", "has_drm": True}],
            {},
        ),
    )
    response = {
        "vl": {
            "vi": [
                {
                    "vid": "fixture",
                    "td": 1800,
                    "br": 1,
                    "ul": {"ui": [{"url": "https://media.example/master.m3u8"}]},
                }
            ]
        },
        "fl": {"fi": [{"br": 1, "drm": 0}]},
    }
    formats, _ = extractor._extract_video_formats_and_subtitles(response, "fixture")
    assert formats == []
    assert extractor._saw_drm


def test_youku_request_reuses_persisted_client_identity(monkeypatch) -> None:
    extractor = _YoukuPersonalIE(YoutubeDL({"quiet": True}))
    monkeypatch.setattr(
        extractor,
        "_get_cookies",
        lambda url: {
            "cna": SimpleNamespace(value="synthetic-stable-client"),
        },
    )
    calls = []

    def fetch(*args, **kwargs):
        calls.append(kwargs)
        return {"data": youku_data()}

    monkeypatch.setattr(InfoExtractor, "_download_json", fetch)
    original = {"utid": "anonymous-generated-client", "vid": "fixture"}
    extractor._download_json(
        "https://ups.youku.com/ups/get.json", "fixture", query=original
    )
    assert calls[0]["query"]["utid"] == "synthetic-stable-client"
    assert original["utid"] == "anonymous-generated-client"


def test_tencent_stops_after_first_usable_cdn_and_retries_failed_mirror(
    monkeypatch,
) -> None:
    extractor = _VQQPersonalIE(YoutubeDL({"quiet": True}))
    extractor._full_duration = 1800
    calls = []

    def manifest(_self, url, *a, **kw):
        calls.append(url)
        return ([], {}) if "failed" in url else ([{"url": url}], {})

    monkeypatch.setattr(InfoExtractor, "_extract_m3u8_formats_and_subtitles", manifest)
    response = {
        "vl": {
            "vi": [
                {
                    "vid": "fixture",
                    "td": 1800,
                    "br": 1,
                    "ul": {
                        "ui": [
                            {"url": f"https://media.example/{name}.m3u8"}
                            for name in ("failed", "working", "unused")
                        ]
                    },
                }
            ]
        },
        "fl": {"fi": [{"br": 1, "drm": 0}]},
    }
    formats, _ = extractor._extract_video_formats_and_subtitles(response, "fixture")
    assert len(formats) == 1
    assert len(calls) == 2
    assert calls[-1].endswith("working.m3u8")
    assert len(response["vl"]["vi"][0]["ul"]["ui"]) == 3


def tencent_inline_response(manifest: str) -> dict:
    return {
        "vl": {
            "vi": [
                {
                    "vid": "fixture",
                    "td": 30,
                    "br": 1,
                    "ul": {
                        "m3u8": manifest,
                        "ui": [{"url": "https://media.example/full.m3u8"}],
                    },
                }
            ]
        },
        "fl": {"fi": [{"br": 1, "drm": 0}]},
    }


INLINE_MANIFEST = (
    "#EXTM3U\n#EXT-X-TARGETDURATION:30\n#EXTINF:30,\npart.ts\n#EXT-X-ENDLIST\n"
)


def test_youku_complete_clear_playlist_uses_bounded_segment_probe():
    extractor = _YoukuPersonalIE(YoutubeDL({"quiet": True}))
    extractor._full_duration = 30
    formats, _ = extractor._parse_m3u8_formats_and_subtitles(
        INLINE_MANIFEST,
        "https://media.example/full.m3u8",
        ext="mp4",
        video_id="fixture",
    )
    assert formats[0]["_framefetch_probe_url"] == "https://media.example/part.ts"
    assert formats[0]["hls_media_playlist_data"] == INLINE_MANIFEST


@pytest.mark.parametrize(
    "manifest",
    [
        INLINE_MANIFEST.replace("#EXTINF:30", "#EXTINF:5"),
        INLINE_MANIFEST.replace("#EXT-X-ENDLIST", ""),
        INLINE_MANIFEST.replace("part.ts", ""),
        INLINE_MANIFEST.replace("#EXTINF:30,", ""),
    ],
)
def test_youku_partial_manifest_cannot_become_full_probe_evidence(
    monkeypatch, manifest
):
    extractor = _YoukuPersonalIE(YoutubeDL({"quiet": True}))
    extractor._full_duration = 30
    monkeypatch.setattr(
        InfoExtractor,
        "_parse_m3u8_formats_and_subtitles",
        lambda *args, **kwargs: pytest.fail("Partial playlist reached parser"),
    )
    with pytest.raises(ExtractorError):
        extractor._parse_m3u8_formats_and_subtitles(
            manifest, "https://media.example/full.m3u8"
        )


@pytest.mark.parametrize(
    "tag", ["#EXT-X-KEY:METHOD=AES-128", "#EXT-X-SESSION-KEY:METHOD=SAMPLE-AES"]
)
def test_personal_extractors_never_request_or_decode_encrypted_media(monkeypatch, tag):
    def unexpected(*args, **kwargs):
        pytest.fail("Protected playlist must not be parsed or request a key")

    monkeypatch.setattr(InfoExtractor, "_parse_m3u8_formats_and_subtitles", unexpected)
    manifest = INLINE_MANIFEST.replace(
        "#EXTINF:", tag + ',URI="https://media.example/key"\n#EXTINF:'
    )
    youku = _YoukuPersonalIE(YoutubeDL({"quiet": True}))
    with pytest.raises(ExtractorError, match="drm_protected"):
        youku._parse_m3u8_formats_and_subtitles(
            manifest, "https://media.example/full.m3u8"
        )
    tencent = _VQQPersonalIE(YoutubeDL({"quiet": True}))
    assert tencent._parse_m3u8_formats_and_subtitles(
        manifest, "https://media.example/full.m3u8"
    ) == ([], {})
    assert tencent._saw_drm is True


def test_tencent_reuses_complete_inline_playlist_without_cdn_request(
    monkeypatch,
) -> None:
    extractor = _VQQPersonalIE(YoutubeDL({"quiet": True}))
    extractor._full_duration = 30

    def unexpected(*args, **kwargs):
        pytest.fail("Inline playlist must not trigger a CDN manifest request")

    monkeypatch.setattr(InfoExtractor, "_request_webpage", unexpected)
    formats, _ = extractor._extract_video_formats_and_subtitles(
        tencent_inline_response(INLINE_MANIFEST), "fixture"
    )
    assert formats[0]["hls_media_playlist_data"] == INLINE_MANIFEST
    assert formats[0]["_framefetch_probe_url"] == "https://media.example/part.ts"
    assert formats[0]["http_headers"]["Referer"] == "https://v.qq.com/"


@pytest.mark.parametrize(
    "manifest, code",
    [
        (
            INLINE_MANIFEST.replace("#EXT-X-ENDLIST", ""),
            "content_access_metadata_invalid",
        ),
        (INLINE_MANIFEST.replace("#EXTINF:30", "#EXTINF:5"), "content_preview_only"),
        ("invalid", "content_access_metadata_invalid"),
    ],
)
def test_tencent_rejects_incomplete_inline_playlist(manifest, code) -> None:
    extractor = _VQQPersonalIE(YoutubeDL({"quiet": True}))
    extractor._full_duration = 30
    with pytest.raises(ExtractorError, match=code):
        extractor._extract_video_formats_and_subtitles(
            tencent_inline_response(manifest), "fixture"
        )


def test_tencent_inline_drm_cannot_be_overwritten_by_clear_api_flag() -> None:
    extractor = _VQQPersonalIE(YoutubeDL({"quiet": True}))
    extractor._full_duration = 30
    manifest = INLINE_MANIFEST.replace(
        "#EXTINF",
        '#EXT-X-KEY:METHOD=SAMPLE-AES,KEYFORMAT="com.apple.streamingkeydelivery",URI="https://media.example/key"\n#EXTINF',
    )
    formats, _ = extractor._extract_video_formats_and_subtitles(
        tencent_inline_response(manifest), "fixture"
    )
    assert formats == []
    assert extractor._saw_drm is True


def test_tencent_metadata_initializes_missing_visitor_guid_without_granting_login(
    monkeypatch,
):
    extractor = _VQQPersonalIE(YoutubeDL({"quiet": True}))
    extractor._source_url = "https://v.qq.com/x/page/fixture.html"
    page = (
        "<script>window.__STARTUP_CONFIG__="
        + json.dumps(
            {
                "vinfoConfig": {
                    "playerVersion": "1.74.0",
                    "adVersion": "4.4.2",
                    "vinfoProtoVer": "7",
                    "adProtoVer": "2026080601",
                    "vinfoProxyDomain": "vd6.l.qq.com",
                }
            }
        )
        + "</script>"
    )
    sent = []

    def fetch(url, vid, *args, **kwargs):
        sent.append(json.loads(kwargs["data"]))
        assert kwargs["headers"]["Cookie"] == sent[-1]["vqqcookie"]
        return {
            "ret": 0,
            "data": {
                "videoInfo": {"vid": "fixture", "duration": 216},
                "playInfo": {"vid": "fixture"},
            },
        }

    monkeypatch.setattr(extractor, "_download_json", fetch)
    extractor._get_webpage_metadata(page, "fixture")
    cookies = extractor._get_cookies("https://v.qq.com/")
    assert len(cookies["video_guid"].value) == 32
    original = cookies["video_guid"].value
    extractor._set_cookie("v.qq.com", "v_vusession", "synthetic-stale-session")
    extractor._get_webpage_metadata(page, "fixture")
    assert extractor._get_cookies("https://v.qq.com/")["video_guid"].value == original
    assert all("video_guid=" in request["vqqcookie"] for request in sent)
    assert all(
        "synthetic-stale-session" not in request["vqqcookie"] for request in sent
    )
    with pytest.raises(ExtractorError, match="login_required"):
        extractor._download_webpage(extractor._API_URL, "fixture")
