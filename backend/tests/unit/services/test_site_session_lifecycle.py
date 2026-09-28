from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from app.services.site_session_lifecycle import (
    SessionEvent,
    decide,
    execution_event,
    expire,
)
from app.services.site_sessions import SiteSessionState, SiteSessionStatus

NOW = datetime(2026, 9, 28, tzinfo=UTC)
S = SiteSessionState


def status(state: SiteSessionState, failures: int = 0, since=NOW) -> SiteSessionStatus:
    return SiteSessionStatus(
        site="youtube.com",
        provider_key="youtube",
        state=state,
        seed_revision=1,
        jar_version=0,
        egress_route="default",
        seeded_at=NOW,
        refreshed_at=None,
        verified_at=None,
        last_error_code=None,
        consecutive_failures=failures,
        state_changed_at=since,
    )


@pytest.mark.parametrize("state", [S.SEEDED, S.VERIFYING, S.READY, S.DEGRADED])
def test_verification_always_restores_ready(state):
    transition = decide(status(state, failures=2), SessionEvent.VERIFIED)
    assert transition.to is S.READY and transition.verified
    assert transition.consecutive_failures == 0
    assert transition.allowed_from == {state}


@pytest.mark.parametrize("state", [S.SEEDED, S.VERIFYING, S.READY, S.DEGRADED])
def test_logout_requires_reimport_immediately(state):
    transition = decide(status(state), SessionEvent.LOGGED_OUT)
    assert transition.requires_reseed
    assert transition.error_code == "session_logged_out"


def test_auth_failures_degrade_then_require_reimport_on_the_third():
    first = decide(
        status(S.READY), SessionEvent.AUTH_FAILURE, error_code="egress_challenged"
    )
    assert (first.to, first.consecutive_failures) == (S.DEGRADED, 1)
    assert first.error_code == "egress_challenged"
    second = decide(status(S.DEGRADED, 1), SessionEvent.AUTH_FAILURE)
    assert (second.to, second.consecutive_failures) == (S.DEGRADED, 2)
    third = decide(status(S.DEGRADED, 2), SessionEvent.AUTH_FAILURE)
    assert third.requires_reseed and third.consecutive_failures == 3


def test_a_new_import_keeps_verifying_through_transient_challenges():
    transition = decide(status(S.VERIFYING, 0), SessionEvent.AUTH_FAILURE)
    assert (transition.to, transition.consecutive_failures) == (S.VERIFYING, 1)
    assert decide(status(S.VERIFYING, 2), SessionEvent.AUTH_FAILURE).requires_reseed


@pytest.mark.parametrize("state", [S.RESEED_REQUIRED, S.REVOKED])
def test_terminal_states_only_change_by_operator_action(state):
    for event in SessionEvent:
        assert decide(status(state), event) is None


def test_degraded_sessions_expire_after_a_day_from_entering_the_state():
    fresh = status(S.DEGRADED, 1, since=NOW - timedelta(hours=23))
    stale = replace(fresh, state_changed_at=NOW - timedelta(hours=24))
    assert expire(fresh, now=NOW) is None
    transition = expire(stale, now=NOW)
    assert transition.requires_reseed and transition.error_code == "degraded_timeout"
    assert expire(replace(stale, state=S.READY), now=NOW) is None


def test_only_identity_failures_count_against_a_session():
    assert execution_event("credential_revoked") is SessionEvent.LOGGED_OUT
    for code in ("credential_expired", "credential_rejected", "egress_challenged"):
        assert execution_event(code) is SessionEvent.AUTH_FAILURE
    for code in ("pot_rejected", "provider_rate_limited", "extractor_regression"):
        assert execution_event(code) is None
