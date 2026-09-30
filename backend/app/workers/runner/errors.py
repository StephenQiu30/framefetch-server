from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Self

from app.services.provider_failures import (
    FailureEvidenceKind,
    FailurePhase,
    FailureScope,
    ProviderFailure,
)
from app.services.provider_types import ProviderAccessContextRef


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
    ) -> None:
        self.code = code
        self.status = status
        self.message = message or code.replace("_", " ")
        self.failure = ProviderFailure.for_code(
            code,
            phase=phase,
            scope=scope,
            evidence_kind=evidence_kind,
            retry_after=retry_after,
            cause_code=cause_code,
        )
        super().__init__(self.message)

    def attributed_to(self, context: ProviderAccessContextRef | None) -> Self:
        if context is None:
            return self
        self.failure = self.failure.with_context(
            context.strategy_id or "legacy", context.generation_id
        )
        return self

    def during(self, phase: FailurePhase) -> Self:
        self.failure = replace(self.failure, phase=phase)
        return self
