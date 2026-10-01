from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.workers.runner.plugins.yt_dlp_plugins.extractor.hongguo_official_share import (
    HongguoOfficialShareIE,
    _is_h5_share_url,
    _is_official_media_url,
)
from yt_dlp.utils import ExtractorError

SERIES_ID = "7662704510720019480"
VIDEO_ID = "7662705589293681726"
SHARE_URL = "https://novelquickapp.com/s/YMc-jWnOo1U/"
H5_URL = "https://novelquickapp.com/hongguo/ug/pages/video-animation-share?x=1"
PLAYER_URL = f"https://hongguoduanju.com/player/{SERIES_ID}/{VIDEO_ID}"
PREVIEW_URL = "https://v3-share.qznovel.com/preview.mp4?start=0&end=30"
MEDIA_URL = "https://v3-hgweb.qznovelvod.com/episode.mp4?signature=redacted"


def share_payload(
    *,
    series_id: str = SERIES_ID,
    video_id: str = VIDEO_ID,
) -> dict[str, Any]:
    return {
        "loaderData": {
            "video-animation-share_page": {
                "linkParams": {
                    "schemeParams": {
                        "video_id": series_id,
                        "vid": video_id,
                    }
                },
                "pageData": {
                    "chapter_order": 1,
                    "chapter_ids": [video_id, "7662705616263072830"],
                    "series_data": {
                        "title": "佳偶错成",
                        "play_url": PREVIEW_URL,
                    },
                },
            }
        }
    }


def player_payload(
    *,
    series_id: str = SERIES_ID,
    video_id: str = VIDEO_ID,
    media_url: str = MEDIA_URL,
) -> dict[str, Any]:
    return {
        "loaderData": {
            "player_(series_id)/(vid)/page": {
                "series_id": series_id,
                "vid": video_id,
                "video_player_info": {
                    "duration": 197.6,
                    "height": "720",
                    "width": "1280",
                    "poster_url": "https://cdn.test/poster.jpg",
                    "main_url": media_url,
                },
                "seriesDetail": {
                    "episode_cnt": 72,
                    "series_id": series_id,
                    "series_name": "佳偶错成",
                    "series_intro": "故事简介",
                    "series_cover": "https://cdn.test/cover.jpg",
                    "vid_list": [video_id, "7662705616263072830"],
                },
            }
        }
    }


def configured_extractor(
    monkeypatch: pytest.MonkeyPatch,
    *,
    share: object = None,
    player: object = None,
) -> HongguoOfficialShareIE:
    extractor = HongguoOfficialShareIE()
    share_state = share if share is not None else share_payload()
    player_state = player if player is not None else player_payload()
    requests: list[str] = []

    def download_handle(url: str, *args: object, **kwargs: object) -> object:
        requests.append(url)
        return "share page", SimpleNamespace(url=H5_URL)

    def download_page(url: str, *args: object, **kwargs: object) -> str:
        requests.append(url)
        return "player page"

    def search_json(
        pattern: str, webpage: str, *args: object, **kwargs: object
    ) -> object:
        return share_state if "share router" in str(args[0]) else player_state

    monkeypatch.setattr(extractor, "_download_webpage_handle", download_handle)
    monkeypatch.setattr(extractor, "_download_webpage", download_page)
    monkeypatch.setattr(extractor, "_search_json", search_json)
    extractor._test_requests = requests  # type: ignore[attr-defined]
    return extractor


def test_extracts_current_episode_from_official_share_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = configured_extractor(monkeypatch)

    info = extractor._real_extract(SHARE_URL)

    assert info["id"] == VIDEO_ID
    assert info["title"] == "佳偶错成 第1集"
    assert info["duration"] == 197.6
    assert info["series_id"] == SERIES_ID
    assert info["episode_number"] == 1
    assert info["formats"][0]["url"] == MEDIA_URL
    assert info["formats"][0]["url"] != PREVIEW_URL
    assert info["formats"][0]["ext"] == "mp4"
    assert info["formats"][0]["http_headers"]["Referer"] == PLAYER_URL
    assert extractor._test_requests == [SHARE_URL, PLAYER_URL]  # type: ignore[attr-defined]


def test_accepts_direct_official_player_url(monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = configured_extractor(monkeypatch)

    info = extractor._real_extract(PLAYER_URL)

    assert info["id"] == VIDEO_ID
    assert extractor._test_requests == [PLAYER_URL]  # type: ignore[attr-defined]


def test_rejects_share_identity_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = configured_extractor(
        monkeypatch,
        share=share_payload(video_id="7662705616263072830"),
    )

    with pytest.raises(ExtractorError, match="identity mismatch"):
        extractor._real_extract(SHARE_URL)


def test_rejects_non_hongguo_media_source(monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = configured_extractor(
        monkeypatch,
        player=player_payload(media_url="https://cdn.example.com/episode.mp4"),
    )

    with pytest.raises(ExtractorError, match="no authorized MP4 source"):
        extractor._real_extract(SHARE_URL)


def test_first_party_url_guards() -> None:
    assert _is_h5_share_url(H5_URL)
    assert not _is_h5_share_url(
        "https://novelquickapp.com.example/hongguo/ug/pages/video-animation-share"
    )
    assert _is_official_media_url(MEDIA_URL)
    assert not _is_official_media_url("https://v3-share.qznovel.com/preview.mp4")


def test_plugin_registers_with_ytdlp() -> None:
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

    assert "HongguoOfficialShare" in result.stderr


@pytest.mark.parametrize(
    "field",
    ["drm", "has_drm", "is_encrypt", "is_encrypted", "decodeKey", "encrypt_key"],
)
def test_protected_hongguo_player_never_exposes_signed_source(monkeypatch, field):

    payload = player_payload()
    payload["loaderData"]["player_(series_id)/(vid)/page"]["video_player_info"][
        field
    ] = "synthetic-protection-marker"
    with pytest.raises(ExtractorError, match="drm_protected"):
        configured_extractor(monkeypatch, player=payload)._real_extract(PLAYER_URL)


@pytest.mark.parametrize(
    "field", ["is_paid", "is_vip", "is_member_only", "requires_purchase"]
)
def test_hongguo_cookie_cannot_expand_public_content_scope(monkeypatch, field):
    payload = player_payload()
    payload["loaderData"]["player_(series_id)/(vid)/page"]["seriesDetail"][field] = True
    with pytest.raises(ExtractorError, match="content_paid_only"):
        configured_extractor(monkeypatch, player=payload)._real_extract(PLAYER_URL)


def test_clear_hongguo_player_accepts_false_protection_flags():
    from app.workers.runner.plugins.yt_dlp_plugins.extractor.hongguo_official_share import (
        _enforce_public_clear,
    )

    _enforce_public_clear(
        {
            "video_player_info": {"drm": 0, "is_encrypt": False},
            "seriesDetail": {"is_vip": False},
        }
    )
