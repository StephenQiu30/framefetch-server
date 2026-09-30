"""Business strategy decisions depend on frozen capabilities and failure facts."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.services.downloads.resolution import (
    ResolutionAction,
    ResolutionPlan,
    decide_resolution,
    failure_signature,
    operation_id,
)
from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_failures import FailurePhase, ProviderFailure
from tests.resolution import capability_for

NOW = datetime(2026, 9, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "code,phase,action,strategy",
    [
        (
            "credential_required",
            FailurePhase.FETCH_METADATA,
            "continue",
            "yt-dlp-session",
        ),
        (
            "egress_challenged",
            FailurePhase.FETCH_METADATA,
            "continue",
            "yt-dlp-session",
        ),
        ("credential_required", FailurePhase.PROBE_MEDIA, "stop", "yt-dlp-anonymous"),
        ("media_probe_failed", FailurePhase.PROBE_MEDIA, "stop", "yt-dlp-anonymous"),
        ("pot_required", FailurePhase.PREPARE_CONTEXT, "stop", "yt-dlp-anonymous"),
        ("content_private", FailurePhase.FETCH_METADATA, "stop", "yt-dlp-anonymous"),
        ("outcome_unknown", FailurePhase.FETCH_METADATA, "stop", "yt-dlp-anonymous"),
        ("network_transient", FailurePhase.PROBE_MEDIA, "retry", "yt-dlp-anonymous"),
        (
            "provider_rate_limited",
            FailurePhase.FETCH_METADATA,
            "retry",
            "yt-dlp-anonymous",
        ),
    ],
)
def test_only_explicit_failure_permissions_can_select_account_strategy(
    code, phase, action, strategy
):
    plan = ResolutionPlan(capability_for(ProviderAccessPolicy.OPERATOR_PUBLIC), 0)
    decision = decide_resolution(
        plan,
        "yt-dlp-anonymous",
        ProviderFailure.for_code(code, phase=phase),
        attempt=1,
        remaining_budget_ms=170000,
        now=NOW,
    )
    assert decision.action.value == action and decision.strategy_id == strategy


def test_rate_limit_retains_original_route_and_retry_after_and_budget_caps_every_path():
    plan = ResolutionPlan(capability_for(ProviderAccessPolicy.OPERATOR_PUBLIC), 0)
    failure = ProviderFailure.for_code(
        "provider_rate_limited", retry_after=NOW + timedelta(minutes=2)
    )
    decision = decide_resolution(
        plan, "yt-dlp-anonymous", failure, attempt=1, remaining_budget_ms=1, now=NOW
    )
    assert decision.retry_at == failure.retry_after
    assert decision.strategy_id == "yt-dlp-anonymous"
    for attempt, budget in ((3, 100), (1, 0)):
        decision = decide_resolution(
            plan,
            "yt-dlp-anonymous",
            failure,
            attempt=attempt,
            remaining_budget_ms=budget,
            now=NOW,
        )
        assert decision.action is ResolutionAction.STOP


def test_clock_change_does_not_manufacture_failure_evidence_or_operation_identity():
    failure = ProviderFailure.for_code("egress_challenged")
    assert failure_signature(failure) == failure_signature(
        replace(failure, observed_at=NOW + timedelta(days=1))
    )
    assert failure_signature(failure) != failure_signature(
        ProviderFailure.for_code("credential_required")
    )
    intent_id = uuid4()
    assert operation_id(intent_id, 0, 1) == operation_id(intent_id, 0, 1)
    assert operation_id(intent_id, 0, 1) != operation_id(intent_id, 1, 1)
    with pytest.raises(ValueError):
        operation_id(intent_id, 0, 4)
