from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from app.services.download_execution.errors import classify_runner_failure
from app.services.downloads.rules.enums import DownloadErrorCode
from app.services.provider_failures import (
    FailureClass,
    FailurePhase,
    FailureScope,
    ProviderFailure,
    parse_retry_after,
)
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_errors import (
    ProviderFailureContext,
    classify_provider_failure,
)


@pytest.mark.parametrize("authenticated", [False, True])
@pytest.mark.parametrize("provider", ["douyin", "youtube", "x", "generic"])
async def test_ambiguous_cookie_and_forbidden_text_never_proves_authentication(
    provider, authenticated
):
    context = ProviderFailureContext(
        provider, "https://example.com/video", authenticated
    )
    for text in (
        b"ERROR: Fresh cookies (not necessarily logged in) are needed",
        b"ERROR: HTTP Error 403: Forbidden",
        b"ERROR: failed to parse JSON",
    ):
        code, _ = classify_provider_failure(context, text)
        failure = ProviderFailure.for_code(code)
        assert failure.failure_class is FailureClass.UPSTREAM_UNCLASSIFIED
        assert failure.scope is not FailureScope.SESSION


@pytest.mark.parametrize(
    "text,code,kind,scope",
    [
        (
            b"PO Token rejected: HTTP Error 403",
            "pot_rejected",
            FailureClass.TOKEN_REJECTED,
            FailureScope.DEPENDENCY,
        ),
        (
            b"PO Token provider unavailable",
            "pot_provider_unavailable",
            FailureClass.TOKEN_UNAVAILABLE,
            FailureScope.DEPENDENCY,
        ),
        (
            b"Sign in to confirm you're not a bot",
            "egress_challenged",
            FailureClass.CHALLENGE_REQUIRED,
            FailureScope.ROUTE,
        ),
        (
            b"Account cookies are no longer valid",
            "credential_expired",
            FailureClass.SESSION_EXPIRED,
            FailureScope.SESSION,
        ),
        (
            b"HTTP Error 429: login required",
            "provider_rate_limited",
            FailureClass.RATE_LIMITED,
            FailureScope.ROUTE,
        ),
        (
            b"Connection reset by peer",
            "network_transient",
            FailureClass.NETWORK_TRANSIENT,
            FailureScope.ROUTE,
        ),
        (
            b"Proxy authentication required",
            "egress_denied",
            FailureClass.EGRESS_DENIED,
            FailureScope.ROUTE,
        ),
        (
            b"Unsupported protocol: sabr",
            "protocol_unavailable",
            FailureClass.PROTOCOL_UNAVAILABLE,
            FailureScope.DEPENDENCY,
        ),
        (
            b"ERROR: This video is private; PO Token required; HTTP Error 429",
            "content_private",
            FailureClass.CONTENT_RESTRICTED,
            FailureScope.CONTENT,
        ),
    ],
)
def test_positive_evidence_separates_failure_causes(text, code, kind, scope):
    context = ProviderFailureContext("youtube", "https://youtu.be/owned", True)
    assert classify_provider_failure(context, text)[0] == code
    failure = ProviderFailure.for_code(code, phase=FailurePhase.PROBE_MEDIA)
    assert failure.failure_class is kind
    assert failure.scope is scope
    assert failure.phase is FailurePhase.PROBE_MEDIA


@pytest.mark.parametrize(
    "code",
    [
        "pot_required",
        "pot_rejected",
        "client_context_mismatch",
        "credential_revoked",
        "upstream_unclassified",
        "network_transient",
        "egress_denied",
    ],
)
def test_download_failure_does_not_turn_dependency_or_context_into_verification(code):
    assert (
        classify_runner_failure(RunnerFailure(code))
        is not DownloadErrorCode.PROVIDER_VERIFICATION_FAILED
    )


@pytest.mark.parametrize(
    "code",
    [
        "credential_access_denied",
        "source_read_timeout",
        "source_read_failed",
        "chrome_profile_unavailable",
    ],
)
def test_source_read_failure_is_not_account_authentication_or_worker_loss(code):
    failure = RunnerFailure(code)
    assert failure.failure.phase is FailurePhase.PREPARE_CONTEXT
    assert failure.failure.scope is FailureScope.SESSION
    assert failure.failure.failure_class is FailureClass.RUNTIME_UNAVAILABLE
    assert (
        classify_runner_failure(failure)
        is DownloadErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE
    )


def test_retry_after_uses_explicit_observation_and_rejects_invalid_values():
    now = datetime(2026, 9, 30, tzinfo=UTC)
    assert parse_retry_after("60", now) == now + timedelta(seconds=60)
    assert parse_retry_after("Wed, 30 Sep 2026 00:02:00 GMT", now) == now + timedelta(
        minutes=2
    )
    for value in (
        None,
        "-1",
        "invalid",
        "9" * 129,
        "9" * 128,
        "Wed, 30 Sep 2026 00:00:00 GMT",
    ):
        assert parse_retry_after(value, now) is None


def test_failure_references_and_timestamps_are_validated():
    failure = ProviderFailure.for_code("media_probe_failed")
    with pytest.raises(ValueError):
        replace(failure, observed_at=datetime(2026, 9, 30))
    with pytest.raises(ValueError):
        replace(failure, diagnostic_ref="https://example.com/raw-response")


def test_explicit_removal_precedes_warning_rate_limit_and_token_hint():
    context = ProviderFailureContext("youtube", "https://youtu.be/owned", True)
    assert classify_provider_failure(
        context,
        b"WARNING: HTTP Error 429; PO Token required\n"
        b"ERROR: This video has been removed",
    ) == ("content_deleted", 422)
