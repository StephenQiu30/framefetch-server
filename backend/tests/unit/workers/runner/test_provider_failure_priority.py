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
