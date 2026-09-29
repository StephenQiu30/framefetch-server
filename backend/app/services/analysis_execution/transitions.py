from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from app.services.analysis.rules.enums import AnalysisErrorCode
from app.services.analysis_execution.errors import (
    AnalysisOwnershipLost,
    AnalysisSourceUnavailable,
)
from app.services.analysis_execution.ports import AnalysisExecutionRepository, Clock


class AnalysisTransitions:
    def __init__(self, repository: AnalysisExecutionRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    async def fail(
        self, job_id: UUID, owner: str, attempt: int, code: AnalysisErrorCode
    ) -> None:
        """Record a failure; the SkillWorkflow waits for any retry it schedules."""
        now = self._clock()
        retry_at = now + _retry_delay(attempt) if code.retryable else None
        try:
            await self._repository.complete_failure(
                job_id,
                owner,
                attempt,
                error_code=code.value,
                error_message=code.value,
                retryable=code.retryable,
                now=now,
                retry_at=retry_at,
            )
        except (AnalysisOwnershipLost, AnalysisSourceUnavailable):
            return


def _retry_delay(attempt: int) -> timedelta:
    return timedelta(seconds=min(300, 5 * (2 ** max(0, attempt - 1))))
