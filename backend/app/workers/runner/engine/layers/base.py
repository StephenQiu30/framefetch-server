"""Layer protocol and bounded, structured failures without raw provider text."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol

from app.services.provider_failures import FailureClass, FailureEvidenceKind
from app.workers.runner.errors import RunnerFailure

if TYPE_CHECKING:
    from app.workers.runner.engine.resolved import ResolvedMedia
    from app.workers.runner.engine.run_context import ResolutionSource, RunContext


class LayerFailure(RunnerFailure):
    def __init__(
        self,
        failure_class: FailureClass,
        gate: Literal["①", "②", "③", "none"],
        evidence: dict[str, str | int | bool | None],
        retry_after: datetime | None = None,
    ) -> None:
        super().__init__(
            failure_class.value,
            gate=gate,
            evidence=evidence,
            evidence_kind=FailureEvidenceKind(str(evidence.get("kind", "unknown"))),
            retry_after=retry_after,
        )

    @classmethod
    def from_runner_failure(cls, error: RunnerFailure) -> LayerFailure:
        result = cls(
            error.failure.failure_class,
            error.failure.gate,
            error.failure.evidence,
            error.failure.retry_after,
        )
        # Keep R0's precise code/status/phase and safe diagnostic facts.
        result.code = error.code
        result.status = error.status
        result.message = error.message
        result.args = error.args
        result.failure = error.failure
        return result


class Layer(Protocol):
    async def resolve(
        self, source: ResolutionSource, ctx: RunContext
    ) -> ResolvedMedia: ...
