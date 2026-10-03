"""Official-share candidate admission preserves legacy public-plugin behavior."""

import json

import pytest
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.wechat_channels_policy import (
    ProtectionScanLimitError,
    enforce_known_restrictions,
    has_protection_material,
    strict_official_video_formats,
    video_formats,
)

MEDIA = "https://finder.video.qq.com/251/20304/stodownload?encfilekey=synthetic"


def test_official_formats_require_probe_and_keep_public_plugin_contract():
    feed = {"h264VideoInfo": {"videoUrl": MEDIA, "width": 1080, "height": 1920}}
    assert video_formats(feed)[0]["vcodec"] == "h264"
    assert strict_official_video_formats(feed) == [
        {
            "format_id": "h264",
            "url": MEDIA,
            "ext": "mp4",
            "vcodec": None,
            "acodec": None,
        }
    ]


@pytest.mark.parametrize(
    "url",
    [
        MEDIA.replace("https:", "http:"),
        MEDIA.replace("finder.video.qq.com", "finder.video.qq.com.evil.example"),
        MEDIA.replace("finder.video.qq.com", "127.0.0.1"),
        MEDIA.replace("finder.video.qq.com", "finder.video.qq.com:8443"),
        MEDIA + "#fragment",
        MEDIA.replace("/20304/", "/../"),
        MEDIA.replace("/20304/", "/%32%30%33%30%34/"),
        MEDIA.replace("/20304/", "//20304/"),
    ],
)
def test_official_formats_reject_unproven_routes(url):
    with pytest.raises(ValueError):
        strict_official_video_formats({"videoUrl": url})


def test_invalid_candidates_are_discarded_but_none_is_failure():
    feed = {
        "h264VideoInfo": {"videoUrl": "https://evil.example/video"},
        "h265VideoInfo": {"videoUrl": MEDIA},
        "videoUrl": MEDIA,
    }
    assert len(strict_official_video_formats(feed)) == 1
    with pytest.raises(ValueError):
        strict_official_video_formats({})


@pytest.mark.parametrize(
    "flag", ["decodeKey", "isDrm", "has_drm", "isEncrypt", "isEncrypted", "encryption"]
)
@pytest.mark.parametrize("value", [True, "1", "unknown", {}, [], 2])
def test_known_protection_flags_never_treat_unknown_values_as_clear(flag, value):
    assert has_protection_material({"nested": [{flag: value}]})


@pytest.mark.parametrize(
    "value", [None, False, 0, "", "0", "false", "FALSE", "none", "null"]
)
def test_explicit_inactive_protection_is_allowed(value):
    assert not has_protection_material(
        {"isEncrypted": value, "encfilekey": "opaque-ticket"}
    )


@pytest.mark.parametrize(
    "flag",
    [
        "isPrivate",
        "isFriendsOnly",
        "isFollowOnly",
        "isFollowerOnly",
        "isChargeContent",
        "isPaid",
        "isPremium",
        "isMemberOnly",
        "isPreview",
        "requiresPurchase",
        "needLogin",
        "needFollow",
        "isGeoRestricted",
        "geoBlocked",
    ],
)
@pytest.mark.parametrize("value", [True, "1", "unknown", {}, []])
def test_nested_explicit_restrictions_and_malformed_flags_are_rejected(flag, value):
    with pytest.raises(RunnerFailure) as caught:
        enforce_known_restrictions({"nested": [{flag: value}]})
    assert caught.value.code == "content_unavailable"


@pytest.mark.parametrize(
    "availability", ["private", "paid", "preview", "subscriber_only", "needs_auth"]
)
def test_nested_known_availability_uses_existing_entitlement_semantics(availability):
    with pytest.raises(RunnerFailure):
        enforce_known_restrictions({"nested": [{"availability": availability}]})


def test_deep_restriction_scan_is_iterative_and_wide_scan_is_bounded():
    payload = json.loads("[" * 600 + '{"isPrivate":true}' + "]" * 600)
    with pytest.raises(RunnerFailure):
        enforce_known_restrictions(payload)
    with pytest.raises(ProtectionScanLimitError):
        enforce_known_restrictions({"wide": [None] * 10_001})
