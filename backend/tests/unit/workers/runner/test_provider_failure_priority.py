"""Design 17 explicit signal precedence."""

import pytest
from app.workers.runner.provider_errors import (
    ProviderFailureContext,
    classify_provider_failure,
)


@pytest.mark.parametrize(
    "message,expected",
    [
        (
            b"This video has been deleted; HTTP Error 429; "
            b"login required. Use --cookies",
            "content_unavailable",
        ),
        (
            b"This video is private; Fresh cookies needed; HTTP Error 429",
            "content_unavailable",
        ),
        (b"Only DRM protected formats; HTTP Error 429", "content_protected"),
        (b"HTTP Error 429; Account cookies are no longer valid", "rate_limited"),
        (b"HTTP Error 429; PO token provider unavailable", "rate_limited"),
        (
            b"Account cookies are no longer valid; "
            b"Fresh cookies needed; HTTP Error 403",
            "login_required",
        ),
        (b"Fresh cookies needed; HTTP Error 403; unable to extract", "challenge"),
        (
            b"Sign in to confirm you're not a bot; This video is unavailable",
            "network_blocked",
        ),
        (b"Sign in to confirm your age", "login_required"),
        (b"SABR-only", "format_unavailable"),
        (b"rate-limit reached or login required", "extractor_broken"),
        (b"empty response", "extractor_broken"),
        (b"This video is unavailable", "extractor_broken"),
        (
            "ERROR: [youtube] s7_qI6_mIXc: 非公開動画; LOGIN_REQUIRED; "
            "Sign in to confirm you're not a bot; HTTP Error 429; "
            "Unable to extract player response".encode(),
            "content_unavailable",
        ),
    ],
)
def test_priority(message, expected):
    context = ProviderFailureContext("youtube", "https://youtu.be/sample", False)
    assert classify_provider_failure(context, message)[0] == expected


def test_datacenter_login_required_is_network_evidence():
    context = ProviderFailureContext(
        "youtube", "https://youtu.be/sample", False, "datacenter"
    )
    assert classify_provider_failure(context, b"LOGIN_REQUIRED")[0] == "network_blocked"
    assert (
        classify_provider_failure(
            context, b"LOGIN_REQUIRED: Sign in to confirm your age"
        )[0]
        == "login_required"
    )
    assert (
        classify_provider_failure(context, b"LOGIN_REQUIRED: This video is private")[0]
        == "content_unavailable"
    )


def test_localized_private_reason_is_youtube_specific():
    context = ProviderFailureContext("vimeo", "https://vimeo.com/123", False)
    assert classify_provider_failure(context, "非公開動画".encode()) is None


@pytest.mark.parametrize(
    "other,expected",
    [
        (b"", None),
        (b"Members-only content", ("content_unavailable", 403)),
        (b"This video has been deleted", ("content_unavailable", 422)),
        (b"HTTP Error 429", ("rate_limited", 429)),
        (b"This video requires login", ("login_required", 422)),
    ],
)
def test_clear_candidate_only_overrides_the_drm_rule(other, expected):
    context = ProviderFailureContext("youtube", "https://youtu.be/sample", False)
    message = b"This format is DRM protected\n" + other
    assert classify_provider_failure(context, message, has_clear_media=True) == expected


@pytest.mark.parametrize(
    "marker,expected",
    [
        ("content_private", "content_unavailable"),
        ("provider_geo_restricted", "network_blocked"),
        ("content_access_metadata_invalid", "content_protected"),
        ("content_preview_only", "content_protected"),
        ("drm_protected", "content_protected"),
    ],
)
def test_dailymotion_restriction_markers(marker, expected):
    context = ProviderFailureContext(
        "dailymotion", "https://www.dailymotion.com/video/x123", False
    )
    assert classify_provider_failure(context, f"framefetch {marker}".encode()) == (
        expected,
        422,
    )
