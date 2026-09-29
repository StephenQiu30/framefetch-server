from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from app.workers.runner.plugins.yt_dlp_plugins.extractor.tiktok_public_player import (
    _TikTokPublicPlayerIE,
    _TikTokPublicShortIE,
)
from yt_dlp.extractor.tiktok import TikTokIE  # type: ignore[import-untyped]
from yt_dlp.networking.exceptions import (  # type: ignore[import-untyped]
    TransportError,
)
from yt_dlp.utils import ExtractorError  # type: ignore[import-untyped]

VIDEO_ID = "7492902606063275294"
VIDEO_URL = f"https://www.tiktok.com/@nba/video/{VIDEO_ID}"
MEDIA_URL = "https://v16m.tiktokcdn.com/video.mp4?signature=redacted"


def player_payload() -> dict[str, Any]:
    return {
        "status_code": 0,
        "items": [
            {
                "id_str": VIDEO_ID,
                "desc": "Yuki is on fire",
                "author_info": {"nickname": "NBA", "unique_id": "nba"},
                "video_info": {
                    "meta": {"duration": 13_100, "width": 576, "height": 1024},
                    "cover": {"url_list": ["https://cdn.test/cover.jpg"]},
                    "profiles": [
                        {
                            "bitrate": 2_419_797,
                            "codec_type": "h264",
                            "fps": 30,
                            "play_addr": {
                                "data_size": 3_961_918,
                                "width": 576,
                                "height": 1024,
                                "url_list": [MEDIA_URL],
                            },
                        }
                    ],
                },
            }
        ],
    }


def test_plugin_registers_as_the_builtin_tiktok_override() -> None:
    assert _TikTokPublicPlayerIE.IE_NAME == "TikTok+public_player"
    assert issubclass(_TikTokPublicPlayerIE, TikTokIE)
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

    assert "public_player (TikTokIE)" in result.stderr
    assert "public_short (TikTokVMIE)" in result.stderr
    assert (
        str(backend_root / "app/workers/runner/plugins/yt_dlp_plugins") in result.stderr
    )


def test_delegates_to_upstream_web_extractor_without_player_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = _TikTokPublicPlayerIE()
    upstream_calls: list[str] = []

    def upstream(_extractor: object, url: str) -> dict[str, object]:
        upstream_calls.append(url)
        return {"id": VIDEO_ID, "formats": []}

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the signed-only player API must not be called")

    monkeypatch.setattr(extractor, "_download_json", forbidden)
    monkeypatch.setattr(_TikTokPublicPlayerIE.__mro__[1], "_real_extract", upstream)

    assert extractor._real_extract(VIDEO_URL)["id"] == VIDEO_ID
    assert upstream_calls == [VIDEO_URL]


@pytest.mark.parametrize(
    ("upstream_error", "message"),
    (
        (
            ExtractorError("Video not available, status code 10204"),
            "TikTok video not available from the official player",
        ),
        (
            ExtractorError("TikTok is requiring login for access to this content"),
            "TikTok video not available from the official player",
        ),
        (
            ExtractorError("Unexpected response from webpage request"),
            "TikTok official player response structure changed",
        ),
        (
            ExtractorError("Unable to solve JS challenge"),
            "TikTok official player response structure changed",
        ),
        (
            ExtractorError("Unable to download webpage", cause=TransportError("reset")),
            "TikTok official player API temporarily unavailable",
        ),
        (
            ExtractorError("Your IP address is blocked from accessing this post"),
            "Your IP address is blocked from accessing this post",
        ),
    ),
)
def test_upstream_failures_map_to_stable_runner_errors(
    monkeypatch: pytest.MonkeyPatch,
    upstream_error: ExtractorError,
    message: str,
) -> None:
    extractor = _TikTokPublicPlayerIE()

    def fail(_extractor: object, _url: str) -> object:
        raise upstream_error

    monkeypatch.setattr(_TikTokPublicPlayerIE.__mro__[1], "_real_extract", fail)

    with pytest.raises(ExtractorError, match=message) as captured:
        extractor._real_extract(VIDEO_URL)

    assert captured.value.expected is True


@pytest.mark.parametrize(
    ("redirected", "expected"),
    (
        (
            "https://www.tiktok.com/@creator/video/7492902606063275294?share=1",
            "https://www.tiktok.com/@creator/video/7492902606063275294",
        ),
        (
            "https://www.tiktok.com/embed/7492902606063275294",
            "https://www.tiktok.com/embed/7492902606063275294",
        ),
    ),
)
def test_short_link_resolves_only_to_public_player_urls(
    monkeypatch: pytest.MonkeyPatch,
    redirected: str,
    expected: str,
) -> None:
    extractor = _TikTokPublicShortIE()
    response = type("Response", (), {"url": redirected})()
    requests: list[dict[str, object]] = []

    def request_webpage(*_args: object, **kwargs: object) -> object:
        requests.append(kwargs)
        return response

    monkeypatch.setattr(
        extractor,
        "_request_webpage",
        request_webpage,
    )

    result = extractor._real_extract("https://vm.tiktok.com/ZTR45GpSF")

    assert result["url"] == expected
    assert result["ie_key"] == _TikTokPublicPlayerIE.ie_key()
    assert requests == [{"note": "Resolving TikTok public video link"}]


def test_short_link_transport_failure_is_temporary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = _TikTokPublicShortIE()

    def fail_transport(*_args: object, **_kwargs: object) -> object:
        raise ExtractorError(
            "Unable to download webpage",
            cause=TransportError("connection reset"),
        )

    monkeypatch.setattr(extractor, "_request_webpage", fail_transport)

    with pytest.raises(
        ExtractorError,
        match="TikTok official player API temporarily unavailable",
    ) as captured:
        extractor._real_extract("https://vm.tiktok.com/ZTR45GpSF")

    assert captured.value.expected is True


def test_short_link_impossible_response_is_an_extractor_regression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = _TikTokPublicShortIE()
    monkeypatch.setattr(
        extractor,
        "_request_webpage",
        lambda *_args, **_kwargs: object(),
    )

    with pytest.raises(
        ExtractorError,
        match="TikTok official player response structure changed",
    ) as captured:
        extractor._real_extract("https://vm.tiktok.com/ZTR45GpSF")

    assert captured.value.expected is True


@pytest.mark.parametrize(
    "redirected",
    (
        "https://www.tiktok.com/@creator/photo/123",
        "https://www.tiktok.com/@creator/live",
        "https://www.tiktok.com/@creator",
        "https://example.com/video/123",
    ),
)
def test_short_link_rejects_non_video_redirect_without_generic_fallback(
    monkeypatch: pytest.MonkeyPatch,
    redirected: str,
) -> None:
    extractor = _TikTokPublicShortIE()
    response = type("Response", (), {"url": redirected})()
    monkeypatch.setattr(
        extractor,
        "_request_webpage",
        lambda *_args, **_kwargs: response,
    )

    with pytest.raises(
        ExtractorError,
        match="TikTok video not available from the official player",
    ) as captured:
        extractor._real_extract("https://vm.tiktok.com/ZTR45GpSF")

    assert captured.value.expected is True
