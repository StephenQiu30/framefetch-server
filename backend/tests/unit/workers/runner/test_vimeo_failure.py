import pytest
from app.workers.runner.provider_errors import (
    ProviderFailureContext,
    classify_provider_failure,
)


def test_vimeo_explicit_password_restriction_is_protected_even_with_clear_candidate():
    context = ProviderFailureContext(
        provider_key="vimeo",
        source_url="https://vimeo.com/68375962",
        authenticated=False,
    )
    message = b"ERROR: This video is protected by a password, use --video-password"
    assert classify_provider_failure(context, message) == ("content_protected", 422)
    assert classify_provider_failure(context, message, has_clear_media=True) == (
        "content_protected",
        422,
    )


def test_vimeo_unknown_fetch_failure_does_not_imply_protection():
    context = ProviderFailureContext(
        provider_key="vimeo",
        source_url="https://vimeo.com/75629013",
        authenticated=False,
    )
    assert classify_provider_failure(context, b"Unable to extract player config") == (
        "extractor_broken",
        502,
    )


@pytest.mark.parametrize(
    "message",
    [
        b"Because of its privacy settings, this video cannot be played here",
        b"Cannot download embed-only video without embedding URL. "
        b"Please call yt-dlp with the URL of the page that embeds this video.",
    ],
)
def test_vimeo_explicit_embed_restriction_precedes_network_or_parser_error(message):
    context = ProviderFailureContext("vimeo", "https://vimeo.com/75629013", False)
    assert classify_provider_failure(
        context, message + b"; HTTP Error 403; Unable to extract player config"
    ) == ("content_unavailable", 403)
    assert classify_provider_failure(context, message, has_clear_media=True) == (
        "content_unavailable",
        403,
    )
