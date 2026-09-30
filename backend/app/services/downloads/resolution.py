"""Immutable execution capabilities and evidence-driven inspection decisions."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_failures import (
    FailureClass,
    FailurePhase,
    FailureScope,
    ProviderFailure,
)
from app.services.provider_types import (
    ProviderAccessContextRef,
    ProviderCapability,
    ProviderSessionSource,
    ResolutionStrategy,
)

_DIGEST = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class ResolutionCapability:
    provider_key: str
    profile_version: str
    access_policy: ProviderAccessPolicy
    content_capabilities: tuple[ProviderCapability, ...]
    strategies: tuple[ResolutionStrategy, ...]
    revision: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", self.provider_key):
            raise ValueError("invalid resolution provider")
        if not self.profile_version or len(self.profile_version) > 128:
            raise ValueError("invalid resolution profile")
        if _DIGEST.fullmatch(self.revision) is None:
            raise ValueError("invalid capability revision")
        ids = tuple(item.strategy_id for item in self.strategies)
        if not ids or len(ids) > 16 or len(set(ids)) != len(ids):
            raise ValueError("invalid resolution strategies")
        if not any(item.enabled for item in self.strategies):
            raise ValueError("no enabled resolution strategy")
        if len(self.content_capabilities) > 32:
            raise ValueError("invalid content capabilities")
        for strategy in self.strategies:
            if (
                self.access_policy is ProviderAccessPolicy.PUBLIC
                and strategy.session_source is not ProviderSessionSource.NONE
            ):
                raise ValueError("public resolution carries an account source")
            if (
                self.access_policy is ProviderAccessPolicy.PERSONAL_ENTITLED
                and strategy.session_source is ProviderSessionSource.NONE
            ):
                raise ValueError("personal resolution has no approved source")


@dataclass(frozen=True, slots=True)
class ResolutionPlan:
    capability: ResolutionCapability
    generation: int
    max_attempts: int = 3
    budget_ms: int = 180_000

    def __post_init__(self) -> None:
        if self.generation < 0 or not 1 <= self.max_attempts <= 3:
            raise ValueError("invalid resolution attempt budget")
        if not 0 < self.budget_ms <= 180_000:
            raise ValueError("invalid resolution time budget")

    @property
    def revision(self) -> str:
        return self.capability.revision

    @property
    def first_strategy(self) -> ResolutionStrategy:
        return next(item for item in self.capability.strategies if item.enabled)

    def strategy(self, strategy_id: str) -> ResolutionStrategy:
        return next(
            item
            for item in self.capability.strategies
            if item.enabled and item.strategy_id == strategy_id
        )


class ResolutionAttemptStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABANDONED = "abandoned"
    OUTCOME_UNKNOWN = "outcome_unknown"


@dataclass(frozen=True, slots=True)
class ResolutionExecution:
    strategy_id: str
    plan_revision: str
    operation_id: str
    context: ProviderAccessContextRef
    runner_instance_id: str
    deadline_at: datetime

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.operation_id) is None:
            raise ValueError("invalid inspection operation identity")
        if _DIGEST.fullmatch(self.plan_revision) is None:
            raise ValueError("invalid inspection plan revision")
        if re.fullmatch(r"[0-9a-f]{32}", self.runner_instance_id) is None:
            raise ValueError("invalid inspection runtime identity")
        if self.context.strategy_id != self.strategy_id:
            raise ValueError("inspection strategy context mismatch")
        if self.deadline_at.tzinfo is None or self.deadline_at.utcoffset() is None:
            raise ValueError("inspection deadline must be timezone aware")


@dataclass(frozen=True, slots=True)
class ResolutionPreparation:
    context: ProviderAccessContextRef
    runner_instance_id: str


class ResolutionAction(StrEnum):
    CONTINUE = "continue"
    RETRY = "retry"
    WAIT = "wait"
    STOP = "stop"


@dataclass(frozen=True, slots=True)
class ResolutionDecision:
    action: ResolutionAction
    strategy_id: str
    retry_at: datetime | None = None


_TRANSIENT = frozenset(
    {
        FailureClass.NETWORK_TRANSIENT,
        FailureClass.RATE_LIMITED,
        FailureClass.RUNTIME_UNAVAILABLE,
        FailureClass.CAPACITY_EXHAUSTED,
    }
)
_HUMAN = frozenset(
    {
        FailureClass.AUTH_REQUIRED,
        FailureClass.SESSION_EXPIRED,
        FailureClass.CHALLENGE_REQUIRED,
    }
)


def decide_resolution(
    plan: ResolutionPlan,
    strategy_id: str,
    failure: ProviderFailure,
    *,
    attempt: int,
    remaining_budget_ms: int,
    now: datetime,
) -> ResolutionDecision:
    """No platform I/O, ambient Registry lookup or account inference."""
    current = plan.strategy(strategy_id)
    stop = ResolutionDecision(ResolutionAction.STOP, strategy_id)
    if attempt >= plan.max_attempts or remaining_budget_ms <= 0:
        return stop
    kind = failure.failure_class
    if (
        kind is FailureClass.RUNTIME_UNAVAILABLE
        and failure.scope is FailureScope.SESSION
        and current.session_source is not ProviderSessionSource.NONE
    ):
        return ResolutionDecision(ResolutionAction.WAIT, strategy_id)
    if kind in _TRANSIENT:
        delay = timedelta(seconds=min(30, 2 ** max(1, attempt)))
        retry_at = max(now + delay, failure.retry_after or now)
        return ResolutionDecision(ResolutionAction.RETRY, strategy_id, retry_at)
    # Session escalation requires metadata evidence; a media probe cannot
    # silently replace the already selected request environment.
    eligible_phase = kind not in _HUMAN or failure.phase is FailurePhase.FETCH_METADATA
    if eligible_phase:
        after_current = False
        for candidate in plan.capability.strategies:
            if candidate.strategy_id == current.strategy_id:
                after_current = True
                continue
            if (
                after_current
                and candidate.enabled
                and kind in candidate.allowed_failure_classes
            ):
                return ResolutionDecision(
                    ResolutionAction.CONTINUE, candidate.strategy_id
                )
    if kind in _HUMAN and current.session_source is not ProviderSessionSource.NONE:
        return ResolutionDecision(ResolutionAction.WAIT, strategy_id)
    return stop


def operation_id(intent_id: UUID, generation: int, attempt_no: int) -> str:
    if generation < 0 or not 1 <= attempt_no <= 3:
        raise ValueError("invalid inspection operation")
    return sha256(f"inspect:{intent_id}:{generation}:{attempt_no}".encode()).hexdigest()


def failure_signature(failure: ProviderFailure) -> str:
    # Observation time is deliberately excluded: another click or a new clock
    # cannot manufacture changed evidence.
    facts = (
        failure.code,
        failure.phase,
        failure.scope,
        failure.failure_class,
        failure.evidence_kind,
        failure.cause_code or "",
        failure.diagnostic_ref or "",
    )
    return sha256("\0".join(facts).encode()).hexdigest()


def unchanged_failure_requires_wait(failure: ProviderFailure) -> bool:
    return failure.failure_class not in _TRANSIENT
