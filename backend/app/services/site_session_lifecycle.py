"""Pure lifecycle decisions for deployment site sessions (Design 046 §5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.services.site_sessions import SiteSessionState, SiteSessionStatus

MAX_CONSECUTIVE_FAILURES = 3
DEGRADED_DEADLINE = timedelta(hours=24)
# A probe that cannot tell logged in from logged out (e.g. an expired token the
# page has not yet turned into "logged out") is unlikely to fix itself; ask the
# source for the login it currently holds instead of waiting a day.
INCONCLUSIVE_DEADLINE = timedelta(minutes=30)

_LIVE = frozenset(
    {
        SiteSessionState.SEEDED,
        SiteSessionState.VERIFYING,
        SiteSessionState.READY,
        SiteSessionState.DEGRADED,
    }
)
# Execution codes that say the identity itself was refused. Proof-of-origin,
# network and extractor failures never count against the session.
_LOGGED_OUT_CODES = frozenset({"credential_revoked"})
_AUTH_FAILURE_CODES = frozenset(
    {
        "credential_expired",
        "credential_rejected",
    }
)


class SessionEvent(StrEnum):
    VERIFIED = "verified"
    LOGGED_OUT = "logged_out"
    AUTH_FAILURE = "auth_failure"
    TEMPORARY_FAILURE = "temporary_failure"


@dataclass(frozen=True, slots=True)
class SessionTransition:
    allowed_from: frozenset[SiteSessionState]
    to: SiteSessionState
    consecutive_failures: int
    error_code: str | None = None
    verified: bool = False

    @property
    def requires_reseed(self) -> bool:
        return self.to is SiteSessionState.RESEED_REQUIRED


def execution_event(error_code: str) -> SessionEvent | None:
    """Map a Runner failure to a session event; unrelated failures return None."""
    if error_code in _LOGGED_OUT_CODES:
        return SessionEvent.LOGGED_OUT
    if error_code in _AUTH_FAILURE_CODES:
        return SessionEvent.AUTH_FAILURE
    if error_code in {
        "egress_challenged",
        "provider_rate_limited",
        "browser_unavailable",
    }:
        return SessionEvent.TEMPORARY_FAILURE
    return None


def decide(
    status: SiteSessionStatus,
    event: SessionEvent,
    *,
    error_code: str | None = None,
) -> SessionTransition | None:
    state = status.state
    if state not in _LIVE:
        # reseed_required and revoked only change through an operator action.
        return None
    current = frozenset({state})
    if event is SessionEvent.VERIFIED:
        return SessionTransition(current, SiteSessionState.READY, 0, verified=True)
    if event is SessionEvent.LOGGED_OUT:
        return SessionTransition(
            current,
            SiteSessionState.RESEED_REQUIRED,
            status.consecutive_failures,
            error_code or "session_logged_out",
        )
    if event is SessionEvent.TEMPORARY_FAILURE:
        return SessionTransition(
            current,
            SiteSessionState.DEGRADED,
            status.consecutive_failures,
            error_code or "browser_unavailable",
        )
    failures = status.consecutive_failures + 1
    code = error_code or "session_auth_failure"
    if failures >= MAX_CONSECUTIVE_FAILURES:
        return SessionTransition(
            current, SiteSessionState.RESEED_REQUIRED, failures, code
        )
    if state is SiteSessionState.READY:
        return SessionTransition(current, SiteSessionState.DEGRADED, failures, code)
    # A new import keeps verifying; a degraded session stays degraded.
    return SessionTransition(current, state, failures, code)


def expire(status: SiteSessionStatus, *, now: datetime) -> SessionTransition | None:
    """Stop retrying a session that has been degraded for too long."""
    if status.state is not SiteSessionState.DEGRADED:
        return None
    age = now - status.state_changed_at
    if status.last_error_code in _AUTH_FAILURE_CODES and age >= DEGRADED_DEADLINE:
        code = "degraded_timeout"
    elif (
        status.last_error_code == "login_probe_inconclusive"
        and age >= INCONCLUSIVE_DEADLINE
    ):
        code = "login_probe_unconfirmed"
    else:
        return None
    return SessionTransition(
        frozenset({SiteSessionState.DEGRADED}),
        SiteSessionState.RESEED_REQUIRED,
        status.consecutive_failures,
        code,
    )
