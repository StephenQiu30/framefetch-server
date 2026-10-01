from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Literal, Self

from app.services.provider_failures import (
    FailureClass,
    FailureEvidenceKind,
    FailurePhase,
    FailureScope,
    ProviderFailure,
    failure_definition,
)
from app.services.provider_types import ExecutionContext


class RunnerFailure(RuntimeError):
    """Stable internal runner failure without provider or URL details."""

    def __init__(
        self,
        code: str,
        *,
        status: int = 422,
        message: str | None = None,
        phase: FailurePhase | None = None,
        scope: FailureScope | None = None,
        evidence_kind: FailureEvidenceKind = FailureEvidenceKind.LOCAL_VALIDATION,
        retry_after: datetime | None = None,
        cause_code: str | None = None,
        gate: Literal["①", "②", "③", "none"] | None = None,
        evidence: dict[str, str | int | bool | None] | None = None,
        stage: Literal["resolve", "download", "validate", "publish"] | None = None,
    ) -> None:
        self.code = code
        self.status = status
        self.message = message or code.replace("_", " ")
        if gate is None:
            kind, _, default_phase = failure_definition(code)
            location = phase or default_phase
            gate = (
                "③"
                if kind is FailureClass.CONTEXT_CHANGED
                or location is FailurePhase.VALIDATE
                else "②"
                if location is FailurePhase.PROBE_MEDIA
                else "①"
                if kind
                in {FailureClass.CONTENT_UNAVAILABLE, FailureClass.CONTENT_PROTECTED}
                else "none"
            )
        self.failure = ProviderFailure.for_code(
            code,
            phase=phase,
            scope=scope,
            evidence_kind=evidence_kind,
            retry_after=retry_after,
            cause_code=cause_code,
            stage=stage,
            gate=gate,
            evidence=evidence,
        )
        super().__init__(self.message)

    def attributed_to(self, context: ExecutionContext | None) -> Self:
        if context is None:
            return self
        self.failure = replace(self.failure, layer=context.resolved_layer)
        return self

    def during(self, phase: FailurePhase) -> Self:
        self.failure = replace(
            self.failure,
            phase=phase,
            gate="③"
            if phase is FailurePhase.VALIDATE
            else "②"
            if phase is FailurePhase.PROBE_MEDIA
            else self.failure.gate,
            stage=(
                "publish"
                if phase is FailurePhase.PUBLISH
                else "validate"
                if phase in {FailurePhase.PROBE_MEDIA, FailurePhase.VALIDATE}
                else "download"
                if phase is FailurePhase.TRANSFER
                else "resolve"
            ),
        )
        return self
