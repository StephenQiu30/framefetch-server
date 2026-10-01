"""The rebuilt engine exposes exactly thirteen failure classes and safe summaries."""

from datetime import UTC, datetime, timedelta

import pytest
from app.schemas.download_intents import IntentFailureResponse
from app.services.download_execution.errors import classify_runner_failure
from app.services.downloads.rules.enums import DownloadErrorCode
from app.services.provider_failures import (
    FailureClass,
    FailurePhase,
    ProviderFailure,
    parse_retry_after,
)
from app.workers.runner.errors import RunnerFailure


@pytest.mark.parametrize("kind", list(FailureClass))
def test_every_engine_failure_has_an_execution_location(kind):
    failure = ProviderFailure.for_code(kind.value, layer="L1")
    assert failure.failure_class is kind
    projection = IntentFailureResponse.from_failure(failure).model_dump()
    assert set(projection) == {
        "code",
        "failure_class",
        "layer",
        "stage",
        "gate",
        "evidence",
        "summary",
    }
    assert projection["stage"] == "resolve"
    assert classify_runner_failure(RunnerFailure(kind.value)) is DownloadErrorCode(
        kind.value
    )


def test_failures_use_only_the_thirteen_design_categories():
    assert {kind.value for kind in FailureClass} == {
        "network_blocked",
        "challenge",
        "login_required",
        "identity_unavailable",
        "rate_limited",
        "context_changed",
        "content_unavailable",
        "content_protected",
        "extractor_broken",
        "format_unavailable",
        "transient",
        "invalid_input",
        "runtime_unavailable",
    }


def test_validation_and_download_failures_keep_stage():
    assert (
        ProviderFailure.for_code("invalid_artifact", phase=FailurePhase.VALIDATE).stage
        == "validate"
    )
    assert (
        ProviderFailure.for_code("transient", phase=FailurePhase.TRANSFER).stage
        == "download"
    )


def test_retry_after_remains_bounded_and_timezone_aware():
    now = datetime(2026, 10, 1, tzinfo=UTC)
    assert parse_retry_after("60", now) == now + timedelta(seconds=60)
    for value in (None, "-1", "invalid", "9" * 129, "9" * 128):
        assert parse_retry_after(value, now) is None


def test_failure_execution_location_is_validated():
    with pytest.raises(ValueError):
        ProviderFailure.for_code("transient", layer="unknown")


def test_publish_failures_keep_stage_and_bounded_evidence():
    failure = ProviderFailure.for_code(
        "publish_failed",
        phase=FailurePhase.PUBLISH,
        gate="③",
        evidence={"kind": "unknown", "cause_code": "storage_unavailable"},
    )
    assert failure.stage == "publish" and failure.gate == "③"
    with pytest.raises(ValueError, match="unsupported facts"):
        ProviderFailure.for_code(
            "transient", evidence={"kind": "unknown", "stderr": "private response"}
        )
    with pytest.raises(ValueError, match="gate"):
        ProviderFailure.for_code("transient", gate="invalid")
