"""Human revisions create a new report version without a model call."""

from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.services.analysis.errors import (
    AnalysisApplicationError,
    AnalysisApplicationErrorCode,
    PersistenceConflict,
    PersistenceIdempotencyConflict,
    PersistenceNotFound,
)
from app.services.analysis.models import AnalysisJobSnapshot, AnalysisJobView
from app.services.analysis.rules.content_document import ContentDraft
from app.services.analysis.validation import (
    validate_idempotency_key,
    validate_owner_hash,
)
from app.services.analysis.views import analysis_job_view
from app.services.quotas import DEFAULT_USER_QUOTA, UserQuota


class ContentRevisionPersistence(Protocol):
    async def revise_content(
        self,
        job_id: UUID,
        owner_hash: str,
        base_report_id: UUID,
        draft: ContentDraft,
        idempotency_key: str,
        *,
        now: datetime,
        quota: UserQuota = DEFAULT_USER_QUOTA,
    ) -> AnalysisJobSnapshot: ...


class ReviseContent:
    def __init__(
        self, repository: ContentRevisionPersistence, clock: Callable[[], datetime]
    ) -> None:
        self._repository = repository
        self._clock = clock

    async def __call__(
        self,
        job_id: UUID,
        owner_hash: str,
        base_report_id: UUID,
        draft: ContentDraft,
        idempotency_key: str,
        *,
        quota: UserQuota = DEFAULT_USER_QUOTA,
    ) -> AnalysisJobView:
        try:
            job = await self._repository.revise_content(
                job_id,
                validate_owner_hash(owner_hash),
                base_report_id,
                draft,
                validate_idempotency_key(idempotency_key),
                now=self._clock(),
                quota=quota,
            )
        except PersistenceNotFound as error:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.NOT_FOUND
            ) from error
        except PersistenceIdempotencyConflict as error:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.IDEMPOTENCY_CONFLICT
            ) from error
        except PersistenceConflict as error:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.INVALID_STATE
            ) from error
        except ValueError as error:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.INVALID_REQUEST
            ) from error
        return analysis_job_view(job)
