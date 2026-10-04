from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.services.analysis.errors import (
    AnalysisApplicationError,
    AnalysisApplicationErrorCode,
    PersistenceActiveRun,
    PersistenceArtifactUnavailable,
    PersistenceConflict,
    PersistenceIdempotencyConflict,
    PersistenceNotFound,
    PersistenceRetryLimited,
)
from app.services.analysis.models import AnalysisJobView, AnalysisRetry
from app.services.analysis.ports import AnalysisRepository, AnalysisSkillCatalog
from app.services.analysis.rules.enums import AnalysisInputKind
from app.services.analysis.validation import (
    validate_idempotency_key,
    validate_now,
    validate_owner_hash,
)
from app.services.analysis.views import analysis_job_view
from app.services.quotas import DEFAULT_USER_QUOTA, UserQuota


class RetryAnalysis:
    def __init__(
        self,
        repository: AnalysisRepository,
        *,
        now: Callable[[], datetime],
        new_id: Callable[[], UUID],
        skill_catalog: AnalysisSkillCatalog,
        max_runs_per_job: int = 10,
        min_interval_seconds: int = 0,
        retries_per_day: int = 20,
    ) -> None:
        self._repository = repository
        self._now = now
        self._new_id = new_id
        self._skill_catalog = skill_catalog
        self._max_runs_per_job = max_runs_per_job
        self._min_interval_seconds = min_interval_seconds
        self._retries_per_day = retries_per_day

    async def __call__(
        self,
        job_id: UUID,
        owner_hash: str,
        idempotency_key: str,
        *,
        quota: UserQuota = DEFAULT_USER_QUOTA,
    ) -> AnalysisJobView:
        owner_hash = validate_owner_hash(owner_hash)
        idempotency_key = validate_idempotency_key(idempotency_key)
        now = validate_now(self._now())
        current = await self._repository.get_job(job_id)
        if current is None or current.owner_hash != owner_hash:
            raise AnalysisApplicationError(AnalysisApplicationErrorCode.NOT_FOUND)
        if current.error_code == "analysis_outcome_unknown":
            raise AnalysisApplicationError(AnalysisApplicationErrorCode.INVALID_STATE)
        if current.input_kind not in {"video", "screenplay"}:
            raise AnalysisApplicationError(AnalysisApplicationErrorCode.INVALID_STATE)
        skill = self._skill_catalog.resolve(
            current.skill_id, AnalysisInputKind(current.input_kind)
        )
        if skill is None:
            raise AnalysisApplicationError(AnalysisApplicationErrorCode.SKILL_OUTDATED)
        if (
            hashlib.sha256(current.skill_instructions.encode()).hexdigest()
            != current.skill_instructions_sha256
        ):
            raise AnalysisApplicationError(AnalysisApplicationErrorCode.INVALID_STATE)
        command = AnalysisRetry(
            job_id=job_id,
            run_id=self._new_id(),
            owner_hash=owner_hash,
            idempotency_key=idempotency_key,
            trigger=(
                "manual_rerun" if current.status == "succeeded" else "manual_retry"
            ),
            outbox_event_id=self._new_id(),
            max_attempts=current.max_attempts,
            max_runs_per_job=self._max_runs_per_job,
            min_interval_seconds=self._min_interval_seconds,
            retries_per_day=self._retries_per_day,
            quota=quota,
        )
        try:
            saved = await self._repository.retry_job_and_enqueue(command, now=now)
        except PersistenceActiveRun as exc:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.ALREADY_ACTIVE
            ) from exc
        except PersistenceArtifactUnavailable as exc:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.ARTIFACT_UNAVAILABLE
            ) from exc
        except PersistenceIdempotencyConflict as exc:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.IDEMPOTENCY_CONFLICT
            ) from exc
        except PersistenceNotFound as exc:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.NOT_FOUND
            ) from exc
        except PersistenceRetryLimited as exc:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.RETRY_LIMITED
            ) from exc
        except PersistenceConflict as exc:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.INVALID_STATE
            ) from exc
        previous_result = await self._repository.get_result(job_id)
        return analysis_job_view(saved.job, result=previous_result)
