from __future__ import annotations

import copy
from io import BytesIO

import pytest
from app.workers.runner.plugins.yt_dlp_plugins.extractor.dailymotion_public import (
    _DailymotionPublicIE,
    clear_manifest_lines,
    clear_vod_manifest,
    public_media_url,
    public_player_metadata,
    public_video_access,
    single_video_result,
)
from yt_dlp import YoutubeDL
from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.extractor.dailymotion import DailymotionBaseInfoExtractor
from yt_dlp.utils import ExtractorError

VIDEO_ID = "xsynthetic1"
MANIFEST_URL = "https://media.example/video/playlist.m3u8"
VOD = """#EXTM3U
#EXT-X-TARGETDURATION:10
#EXT-X-PLAYLIST-TYPE:VOD
#EXTINF:10,
one.ts
#EXTINF:10,
two.ts
#EXT-X-ENDLIST
"""


def public_metadata() -> dict[str, object]:
    # Documented API contract, not a captured platform response or live evidence.
    return {
        "id": VIDEO_ID,
        "private": False,
        "password_protected": False,
        "published": True,
        "status": "published",
        "geoblocking": [],
        "duration": 20,
    }


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "private",
        "password_protected",
        "published",
        "status",
        "duration",
        "geoblocking",
    ],
)
def test_missing_public_evidence_is_not_assumed(field: str) -> None:
    payload = public_metadata()
    del payload[field]
    with pytest.raises(ExtractorError, match="content_access_metadata_invalid"):
        public_video_access(payload, VIDEO_ID)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("id", "xother", "content_access_metadata_invalid"),
        ("private", True, "content_private"),
        ("password_protected", True, "content_private"),
        ("private", "false", "content_access_metadata_invalid"),
        ("password_protected", 0, "content_access_metadata_invalid"),
        ("published", 1, "content_access_metadata_invalid"),
        ("published", False, "content_access_metadata_invalid"),
        ("status", "deleted", "content_access_metadata_invalid"),
        ("duration", True, "content_access_metadata_invalid"),
        ("duration", float("nan"), "content_access_metadata_invalid"),
        ("duration", 0, "content_access_metadata_invalid"),
        ("geoblocking", None, "content_access_metadata_invalid"),
        ("geoblocking", ["allow", "US"], "provider_geo_restricted"),
        ("geoblocking", ["deny", "FR"], "provider_geo_restricted"),
    ],
)
def test_restricted_or_ambiguous_public_metadata_rejected(
    field: str, value: object, reason: str
) -> None:
    payload = public_metadata()
    payload[field] = value
    with pytest.raises(ExtractorError, match=reason):
        public_video_access(payload, VIDEO_ID)


def test_documented_global_publication_and_duration() -> None:
    payload = public_metadata()
    assert public_video_access(payload, VIDEO_ID) == 20
    payload["geoblocking"] = ["allow"]
    assert public_video_access(payload, VIDEO_ID) == 20


def test_private_id_does_not_enter_public_metadata_path() -> None:
    with pytest.raises(ExtractorError, match="content_access_metadata_invalid"):
        public_video_access(public_metadata(), "kprivate")


@pytest.mark.parametrize(
    "tag",
    [
        '#EXT-X-KEY:METHOD=AES-128,URI="key.bin"',
        '#EXT-X-KEY:METHOD=SAMPLE-AES,URI="license"',
        '#EXT-X-SESSION-KEY:METHOD=AES-128,URI="key.bin"',
        "#EXT-X-KEY:METHOD=NONE",
        '#EXT-X-KEY METHOD=AES-128,URI="key.bin"',
        '#EXT-X-KEY\tMETHOD=AES-128,URI="key.bin"',
        '#EXT-X-SESSION-KEY METHOD=AES-128,URI="key.bin"',
        '#ext-x-key:METHOD=AES-128,URI="key.bin"',
    ],
)
def test_protection_rejected_for_master_and_media_manifest(tag: str) -> None:
    master = "#EXTM3U\n" + tag + "\n#EXT-X-STREAM-INF:BANDWIDTH=400000\nfull.m3u8\n"
    for manifest in (master, VOD.replace("#EXTM3U", "#EXTM3U\n" + tag)):
        with pytest.raises(ExtractorError, match="drm_protected"):
            clear_manifest_lines(manifest)


@pytest.mark.parametrize(
    "document,reason",
    [
        (VOD.replace("#EXT-X-ENDLIST", ""), "content_access_metadata_invalid"),
        (
            VOD.replace("#EXT-X-TARGETDURATION:10", ""),
            "content_access_metadata_invalid",
        ),
        (VOD.replace("#EXTINF:10,", "#EXTINF:1,"), "content_preview_only"),
        (
            VOD.replace("#EXTINF:10,\none.ts", "one.ts"),
            "content_access_metadata_invalid",
        ),
        (
            VOD.replace("one.ts", "data:text/plain,media"),
            "content_access_metadata_invalid",
        ),
        ("<html>challenge</html>", "content_access_metadata_invalid"),
        ("#EXTM3U\n" + "x" * 2_000_000, "content_access_metadata_invalid"),
    ],
)
def test_live_partial_malformed_or_unbounded_playlists_rejected(
    document: str, reason: str
) -> None:
    with pytest.raises(ExtractorError, match=reason):
        clear_vod_manifest(document, MANIFEST_URL, 20)


def test_full_vod_is_bound_to_original_duration() -> None:
    assert clear_vod_manifest(VOD, MANIFEST_URL, 20) == (
        "https://media.example/video/one.ts"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/video.ts",
        "https://192.168.1.1/video.ts",
        "https://[::1]/video.ts",
        "https://media.internal/video.ts",
        "https://media.local/video.ts",
        "https://localhost/video.ts",
        "https://media.example:19101/video.ts",
        "https://user:password@media.example/video.ts",
        "file:///tmp/video.ts",
        "https://media.example\\@127.0.0.1/video.ts",
        "https://media.example/video\nts",
    ],
)
def test_non_public_segment_and_manifest_authorities_rejected(url: str) -> None:
    with pytest.raises(ExtractorError, match="content_access_metadata_invalid"):
        public_media_url(url)
    with pytest.raises(ExtractorError, match="content_access_metadata_invalid"):
        clear_vod_manifest(VOD.replace("one.ts", url), MANIFEST_URL, 20)


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"id": "xother"}, "content_access_metadata_invalid"),
        ({"entries": []}, "content_access_metadata_invalid"),
        ({"_type": "playlist"}, "content_access_metadata_invalid"),
        ({"is_live": True}, "content_access_metadata_invalid"),
        ({"is_live": "false"}, "content_access_metadata_invalid"),
        ({"live_status": "was_live"}, "content_access_metadata_invalid"),
        ({"duration": 5}, "content_preview_only"),
        ({"formats": []}, "content_access_metadata_invalid"),
    ],
)
def test_upstream_collection_live_wrong_asset_and_preview_do_not_pass(
    change: dict[str, object], reason: str
) -> None:
    payload = {"id": VIDEO_ID, "duration": 20, "formats": [{"url": MANIFEST_URL}]}
    payload.update(change)
    with pytest.raises(ExtractorError, match=reason):
        single_video_result(payload, VIDEO_ID, 20)


def player_metadata() -> dict[str, object]:
    # Current observed key/value shapes, with synthetic identity, duration and URL.
    return {
        "id": VIDEO_ID,
        "private": False,
        "is_password_protected": False,
        "protected_delivery": False,
        "mode": "vod",
        "stream_type": "recorded",
        "media_type": "video",
        "stream_formats": {"720": "mpegts"},
        "duration": 20,
        "title": "Synthetic recorded video",
        "qualities": {"auto": [{"type": "application/x-mpegURL", "url": MANIFEST_URL}]},
    }


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "private",
        "is_password_protected",
        "protected_delivery",
        "mode",
        "stream_type",
        "media_type",
        "stream_formats",
        "duration",
    ],
)
def test_player_missing_evidence_never_becomes_anonymous_access(field: str) -> None:
    payload = player_metadata()
    del payload[field]
    with pytest.raises(ExtractorError, match="content_access_metadata_invalid"):
        public_player_metadata(payload, VIDEO_ID, 20)


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"private": True}, "content_private"),
        ({"is_password_protected": True}, "content_private"),
        ({"protected_delivery": True}, "drm_protected"),
        ({"mode": "live"}, "content_access_metadata_invalid"),
        ({"stream_type": "live"}, "content_access_metadata_invalid"),
        ({"media_type": "audio"}, "content_access_metadata_invalid"),
        ({"stream_formats": {"720": "dash"}}, "content_access_metadata_invalid"),
        ({"id": "xother"}, "content_access_metadata_invalid"),
        ({"duration": 1}, "content_preview_only"),
        ({"is_paid": True}, "content_paid_only"),
        ({"requires_purchase": True}, "content_paid_only"),
        ({"is_preview": True}, "content_preview_only"),
        ({"has_drm": True}, "drm_protected"),
    ],
)
def test_player_restrictions_survive_before_formats_are_exposed(
    change: dict[str, object], reason: str
) -> None:
    payload = player_metadata()
    payload.update(change)
    with pytest.raises(ExtractorError, match=reason):
        public_player_metadata(payload, VIDEO_ID, 20)


class ManifestResponse(BytesIO):
    def __init__(self, document: str, url: str) -> None:
        super().__init__(document.encode())
        self.url = url
        self.requested_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.requested_sizes.append(size)
        return super().read(size)


def mocked_extractor(
    monkeypatch: pytest.MonkeyPatch,
    *,
    access: dict[str, object] | None = None,
    player: dict[str, object] | None = None,
    manifests: dict[str, str] | None = None,
    redirects: dict[str, str] | None = None,
) -> tuple[_DailymotionPublicIE, list[str], list[ManifestResponse]]:
    extractor = _DailymotionPublicIE(YoutubeDL({"quiet": True}))
    requests: list[str] = []
    responses: list[ManifestResponse] = []
    access_data = public_metadata() if access is None else access
    player_data = player_metadata() if player is None else player
    documents = {MANIFEST_URL: VOD} if manifests is None else manifests

    def json_response(_self, url, *args, **kwargs):
        requests.append(url)
        if url == f"https://api.dailymotion.com/video/{VIDEO_ID}":
            assert kwargs["query"]["fields"] == (
                "id,private,password_protected,published,status,duration,geoblocking"
            )
            return copy.deepcopy(access_data)
        assert url == f"https://www.dailymotion.com/player/metadata/video/{VIDEO_ID}"
        return copy.deepcopy(player_data)

    def graph_response(_self, *args, **kwargs):
        requests.append("graphql")
        return {"xid": VIDEO_ID, "description": "Synthetic public video"}

    def manifest_response(_self, url, *args, **kwargs):
        requests.append(url)
        assert url in documents, "Unexpected media, key, or license request"
        response = ManifestResponse(documents[url], (redirects or {}).get(url, url))
        responses.append(response)
        return response

    monkeypatch.setattr(InfoExtractor, "_download_json", json_response)
    monkeypatch.setattr(DailymotionBaseInfoExtractor, "_call_api", graph_response)
    monkeypatch.setattr(InfoExtractor, "_request_webpage", manifest_response)
    return extractor, requests, responses


def test_real_upstream_extractor_retained_and_download_receives_checked_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor, requests, responses = mocked_extractor(monkeypatch)
    result = extractor._real_extract(f"https://www.dailymotion.com/video/{VIDEO_ID}")
    assert result["id"] == VIDEO_ID
    assert result["duration"] == 20
    assert result["availability"] == "public"
    assert result["_framefetch_full_stream"] is True
    assert result["formats"][0]["hls_media_playlist_data"] == VOD
    assert result["formats"][0]["_framefetch_probe_url"].endswith("/one.ts")
    assert requests == [
        f"https://api.dailymotion.com/video/{VIDEO_ID}",
        "graphql",
        f"https://www.dailymotion.com/player/metadata/video/{VIDEO_ID}",
        MANIFEST_URL,
    ]
    assert all(response.closed for response in responses)
    assert all(response.requested_sizes == [2_000_001] for response in responses)


def test_public_gate_stops_before_player_or_media_request(monkeypatch) -> None:
    access = public_metadata()
    access["private"] = True
    extractor, requests, _ = mocked_extractor(monkeypatch, access=access)
    with pytest.raises(ExtractorError, match="content_private"):
        extractor._real_extract(f"https://www.dailymotion.com/video/{VIDEO_ID}")
    assert requests == [f"https://api.dailymotion.com/video/{VIDEO_ID}"]


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"private": True}, "content_private"),
        ({"protected_delivery": True}, "drm_protected"),
        ({"is_preview": True}, "content_preview_only"),
        ({"mode": "live"}, "content_access_metadata_invalid"),
    ],
)
def test_player_gate_stops_before_any_manifest_or_media(
    monkeypatch, change, reason
) -> None:
    player = player_metadata()
    player.update(change)
    extractor, requests, _ = mocked_extractor(monkeypatch, player=player)
    with pytest.raises(ExtractorError, match=reason):
        extractor._real_extract(f"https://www.dailymotion.com/video/{VIDEO_ID}")
    assert len(requests) == 3


MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=1280x720,CODECS="avc1.64001f,mp4a.40.2"
full.m3u8
"""
VARIANT_URL = "https://media.example/video/full.m3u8"


@pytest.mark.parametrize("encrypted_master", [True, False])
@pytest.mark.parametrize("separator", [":", " ", "\t"])
def test_master_and_actual_variant_checked_before_any_key_request(
    monkeypatch, encrypted_master, separator
) -> None:
    protection = f'#EXT-X-KEY{separator}METHOD=AES-128,URI="key.bin"\n'
    master = MASTER.replace("#EXTM3U\n", "#EXTM3U\n" + protection)
    variant = VOD.replace("#EXTM3U\n", "#EXTM3U\n" + protection)
    documents = {
        MANIFEST_URL: master if encrypted_master else MASTER,
        VARIANT_URL: VOD if encrypted_master else variant,
    }
    extractor, requests, _ = mocked_extractor(monkeypatch, manifests=documents)
    with pytest.raises(ExtractorError, match="drm_protected"):
        extractor._real_extract(f"https://www.dailymotion.com/video/{VIDEO_ID}")
    assert all("key.bin" not in url for url in requests)
    assert (VARIANT_URL in requests) is not encrypted_master


def test_master_resolves_each_clear_variant_and_attaches_the_exact_checked_data(
    monkeypatch,
) -> None:
    extractor, requests, _ = mocked_extractor(
        monkeypatch, manifests={MANIFEST_URL: MASTER, VARIANT_URL: VOD}
    )
    result = extractor._real_extract(f"https://www.dailymotion.com/video/{VIDEO_ID}")
    assert requests[-2:] == [MANIFEST_URL, VARIANT_URL]
    assert result["formats"][0]["url"] == VARIANT_URL
    assert result["formats"][0]["hls_media_playlist_data"] == VOD


def test_master_and_variant_relative_urls_use_each_final_response_url(monkeypatch):
    final_master = "https://cdn.example/redirect/master.m3u8"
    redirected_variant = "https://cdn.example/redirect/full.m3u8"
    final_variant = "https://other-cdn.example/actual/playlist.m3u8"
    extractor, requests, _ = mocked_extractor(
        monkeypatch,
        manifests={MANIFEST_URL: MASTER, redirected_variant: VOD},
        redirects={MANIFEST_URL: final_master, redirected_variant: final_variant},
    )
    result = extractor._real_extract(f"https://www.dailymotion.com/video/{VIDEO_ID}")
    assert requests[-2:] == [MANIFEST_URL, redirected_variant]
    assert result["formats"][0]["url"] == final_variant
    assert result["formats"][0]["hls_media_playlist_data"] == VOD
    assert result["formats"][0]["_framefetch_probe_url"] == (
        "https://other-cdn.example/actual/one.ts"
    )


@pytest.mark.parametrize("in_master", [True, False])
@pytest.mark.parametrize(
    "tag",
    [
        '#EXT-X-MAP:URI="unverified-init.mp4"',
        "#EXT-X-BYTERANGE:200@0",
        '#EXT-X-PART:DURATION=1,URI="unverified-part.ts"',
        '#EXT-X-PRELOAD-HINT:TYPE=PART,URI="unverified-part.ts"',
        '#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=100000,URI="unverified-iframe.m3u8"',
        "#EXT-X-I-FRAMES-ONLY",
        "#EXT-X-GAP",
        "#EXT-X-SKIP:SKIPPED-SEGMENTS=2",
    ],
)
def test_unverified_hls_structures_rejected_before_extra_media_requests(
    monkeypatch, in_master, tag
):
    master = MASTER.replace("#EXTM3U\n", "#EXTM3U\n" + tag + "\n")
    variant = VOD.replace("#EXTM3U\n", "#EXTM3U\n" + tag + "\n")
    extractor, requests, _ = mocked_extractor(
        monkeypatch,
        manifests={
            MANIFEST_URL: master if in_master else MASTER,
            VARIANT_URL: VOD if in_master else variant,
        },
    )
    with pytest.raises(ExtractorError, match="content_access_metadata_invalid"):
        extractor._real_extract(f"https://www.dailymotion.com/video/{VIDEO_ID}")
    assert all("unverified" not in url for url in requests)
    assert (VARIANT_URL in requests) is not in_master


def test_unimplemented_dash_does_not_reach_media_requests(monkeypatch) -> None:
    player = player_metadata()
    player["qualities"] = {
        "auto": [{"type": "application/dash+xml", "url": "https://media.example/a.mpd"}]
    }
    extractor, requests, _ = mocked_extractor(monkeypatch, player=player)
    with pytest.raises(ExtractorError, match="content_access_metadata_invalid"):
        extractor._real_extract(f"https://www.dailymotion.com/video/{VIDEO_ID}")
    assert len(requests) == 3
