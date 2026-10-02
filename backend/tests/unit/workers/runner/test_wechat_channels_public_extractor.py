from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from app.workers.runner.plugins.yt_dlp_plugins.extractor.wechat_channels_public import (
    WechatChannelsPublicIE,
)
from app.workers.runner.wechat_channels_policy import (
    allowed_media_url,
    has_protection_material,
)
from yt_dlp.utils import ExtractorError

VIDEO_ID = "AFWYoXF5Bw"
SHARE_URL = f"https://weixin.qq.com/sph/{VIDEO_ID}"
MEDIA_URL = "https://finder.video.qq.com/251/20304/stodownload?encfilekey=public"


def feed_payload(
    *, video_url: str | None = None, decode_key: str = ""
) -> dict[str, Any]:
    feed: dict[str, Any] = {
        "description": "Public Channels video",
        "coverUrl": "https://wx.qpic.cn/cover.jpg",
    }
    if video_url is not None:
        feed["h264VideoInfo"] = {
            "videoUrl": video_url,
            "width": 1080,
            "height": 1920,
            "decodeKey": decode_key,
        }
    return {
        "errCode": 0,
        "data": {
            "authorInfo": {"nickname": "Public creator"},
            "feedInfo": feed,
        },
    }


def configured_extractor(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[object],
) -> tuple[WechatChannelsPublicIE, list[str]]:
    extractor = WechatChannelsPublicIE()
    requests: list[str] = []
    monkeypatch.setattr(extractor, "_download_webpage", lambda *args, **kwargs: "ok")

    def download_json(url: str, *args: object, **kwargs: object) -> object:
        requests.append(url)
        return responses.pop(0)

    monkeypatch.setattr(extractor, "_download_json", download_json)
    return extractor, requests


def test_public_share_extracts_directly_exposed_clear_media(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor, requests = configured_extractor(
        monkeypatch,
        [feed_payload(video_url=MEDIA_URL)],
    )

    info = extractor._real_extract(SHARE_URL)

    assert requests == [
        "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info",
    ]
    assert info["id"] == VIDEO_ID
    assert info["title"] == "Public Channels video"
    assert info["uploader"] == "Public creator"
    assert info["formats"][0]["url"] == MEDIA_URL
    assert info["formats"][0]["vcodec"] == "h264"


def test_public_share_without_direct_media_requires_the_declared_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor, requests = configured_extractor(monkeypatch, [feed_payload()])
    monkeypatch.setattr(extractor, "_get_cookies", lambda _url: {})

    with pytest.raises(ExtractorError, match="login_required"):
        extractor._real_extract(SHARE_URL)

    assert requests == [
        "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"
    ]


def test_unavailable_public_share_never_uses_operator_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor, requests = configured_extractor(
        monkeypatch, [{"errCode": -1, "data": {}}]
    )

    with pytest.raises(ExtractorError, match="public link unavailable"):
        extractor._real_extract(SHARE_URL)

    assert len(requests) == 1


def test_rejects_protected_public_media(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protected, _ = configured_extractor(
        monkeypatch,
        [feed_payload(video_url=MEDIA_URL, decode_key="secret")],
    )
    with pytest.raises(ExtractorError, match="DRM protected"):
        protected._real_extract(SHARE_URL)


def test_parser_helpers_fail_closed() -> None:
    assert allowed_media_url(MEDIA_URL)
    assert not allowed_media_url(
        "https://finder.video.qq.com.evil.test/251/1/stodownload"
    )
    assert not allowed_media_url("http://finder.video.qq.com/251/1/stodownload")
    assert has_protection_material({"data": {"decodeKey": "secret"}})
    assert not has_protection_material({"data": {"decodeKey": ""}})


@pytest.mark.parametrize(
    "media_url",
    [
        MEDIA_URL,
        "https://finder.video.qq.com:443/251/1/stodownload?file=synthetic",
    ],
)
def test_media_url_allows_only_the_official_standard_https_origin(
    media_url: str,
) -> None:
    assert allowed_media_url(media_url)


@pytest.mark.parametrize(
    "media_url",
    [
        None,
        "https://finder.video.qq.com:invalid/251/1/stodownload",
        "https://finder.video.qq.com:65536/251/1/stodownload",
        "https://finder.video.qq.com:/251/1/stodownload",
        "https://finder.video.qq.com:444/251/1/stodownload",
        "https://synthetic@finder.video.qq.com/251/1/stodownload",
        "https://synthetic:password@finder.video.qq.com/251/1/stodownload",
        "https://@finder.video.qq.com/251/1/stodownload",
        "https://finder.video.qq.com/251/1/sto\ndownload",
        "https://finder.video.qq.com/251/1/sto\tdownload",
        "https://finder.video.qq.com/251/1/sto download",
        "https://finder.video.qq.com/251/1/sto\u00a0download",
        "https://finder.video.qq.com/251/1/stodownload?file=synthetic\x00",
        "https://finder.video.qq.com/251/1/stodownload?file=synthetic\x7f",
        " https://finder.video.qq.com/251/1/stodownload",
        "https://finder.video.qq.com/251/1/stodownload ",
        "https://finder.video.qq.com./251/1/stodownload",
        "https://finder.video.qq.com/251/1/stodownload?file=synthetic\\suffix",
        "https://[finder.video.qq.com/251/1/stodownload",
    ],
)
def test_media_url_rejects_ambiguous_or_malformed_values_without_raising(
    media_url: object,
) -> None:
    assert not allowed_media_url(media_url)


def test_malformed_media_url_stays_a_declared_extractor_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor, _ = configured_extractor(
        monkeypatch,
        [
            feed_payload(
                video_url="https://finder.video.qq.com:invalid/251/1/stodownload"
            )
        ],
    )

    with pytest.raises(ExtractorError, match="login_required"):
        extractor._real_extract(SHARE_URL)


def test_plugin_registers_with_ytdlp_offline() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    # The CLI lists extractors before its normal plugin loading. Use yt-dlp's
    # loader first, then exercise the offline listing without a source URL.
    loader = (
        "import sys\n"
        "import yt_dlp\n"
        "from yt_dlp.globals import plugin_dirs\n"
        "from yt_dlp.plugins import load_all_plugins\n"
        "_, opts, _, _ = yt_dlp.parse_options(sys.argv[1:])\n"
        "plugin_dirs.value = opts.plugin_dirs\n"
        "load_all_plugins()\n"
        "yt_dlp.main(sys.argv[1:])\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            loader,
            "--ignore-config",
            "--plugin-dirs",
            str(backend_root / "app/workers/runner"),
            "--list-extractors",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0
    assert WechatChannelsPublicIE.IE_NAME in result.stdout.splitlines()


def test_missing_declared_session_is_an_explicit_auth_failure():
    from app.workers.runner.provider_errors import (
        ProviderFailureContext,
        classify_provider_failure,
    )

    error = classify_provider_failure(
        ProviderFailureContext("wechat_channels", SHARE_URL, False),
        (
            b"FrameFetch login_required: this WeChat Channels video "
            b"needs account identity"
        ),
    )
    assert error == ("login_required", 422)
