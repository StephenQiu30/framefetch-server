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
    preparation_failure_is_terminal,
    unchanged_failure_is_terminal,
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


def test_session_recovery_has_a_finite_automatic_timer_on_the_same_strategy():
    plan = ResolutionPlan(capability_for(ProviderAccessPolicy.PERSONAL_ENTITLED), 0)
    for code in (
        "provider_session_not_ready",
        "credential_expired",
        "credential_required",
    ):
        decision = decide_resolution(
            plan,
            "yt-dlp-session",
            ProviderFailure.for_code(code),
            attempt=1,
            remaining_budget_ms=170000,
            now=NOW,
        )
        assert decision.action is ResolutionAction.WAIT
        assert decision.retry_at == NOW + timedelta(seconds=15)
        assert decision.strategy_id == "yt-dlp-session"


@pytest.mark.parametrize(
    "code",
    ["credential_access_denied", "chrome_profile_unavailable", "source_read_failed"],
)
@pytest.mark.parametrize(
    "policy", [ProviderAccessPolicy.PUBLIC, ProviderAccessPolicy.PERSONAL_ENTITLED]
)
def test_static_source_preparation_failure_cannot_retry_or_choose_another_route(
    code, policy
):
    plan = ResolutionPlan(capability_for(policy), 0)
    failure = ProviderFailure.for_code(code)
    selected = plan.first_strategy.strategy_id
    decision = decide_resolution(
        plan, selected, failure, attempt=0, remaining_budget_ms=180000, now=NOW
    )
    assert decision.action is ResolutionAction.STOP
    assert decision.strategy_id == selected and decision.retry_at is None
    assert preparation_failure_is_terminal(failure)
    assert unchanged_failure_is_terminal(failure)


def test_source_read_timeout_waits_on_selected_session_with_original_budget_caps():
    plan = ResolutionPlan(capability_for(ProviderAccessPolicy.PERSONAL_ENTITLED), 0)
    failure = ProviderFailure.for_code("source_read_timeout")
    selected = plan.first_strategy.strategy_id
    decision = decide_resolution(
        plan, selected, failure, attempt=0, remaining_budget_ms=180000, now=NOW
    )
    assert decision.action is ResolutionAction.WAIT
    assert decision.strategy_id == selected
    assert decision.retry_at == NOW + timedelta(seconds=15)
    assert not preparation_failure_is_terminal(failure)
    assert not unchanged_failure_is_terminal(failure)
    for attempt, budget in ((3, 180000), (0, 0)):
        exhausted = decide_resolution(
            plan,
            selected,
            failure,
            attempt=attempt,
            remaining_budget_ms=budget,
            now=NOW,
        )
        assert exhausted.action is ResolutionAction.STOP


def test_static_source_rule_is_limited_to_context_preparation():
    failure = ProviderFailure.for_code(
        "source_read_failed", phase=FailurePhase.FETCH_METADATA
    )
    assert not preparation_failure_is_terminal(failure)
