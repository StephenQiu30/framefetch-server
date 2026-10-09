from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.services.downloads.download_models import (
    DEFAULT_MAX_ATTEMPTS,
    DownloadCreate,
    DownloadView,
)
from app.services.downloads.errors import (
    ApplicationError,
    ApplicationErrorCode,
    PersistenceConflict,
    PersistenceIdempotencyConflict,
    PersistenceNotFound,
)
from app.services.downloads.ports import DownloadRepository, RequestFingerprinter
from app.services.downloads.queries import _owned_job
from app.services.downloads.rules.enums import (
    DownloadErrorCode,
    DownloadSourceKind,
    DownloadStatus,
)
from app.services.downloads.validation import (
    validate_idempotency_key,
    validate_now,
    validate_owner_hash,
)
from app.services.downloads.views import download_view
from app.services.quotas import DEFAULT_USER_QUOTA, UserQuota


class RetryDownload:
    """Create a new attempt resource from a terminal download's source selection."""

    def __init__(
        self,
        *,
        repository: DownloadRepository,
        fingerprinter: RequestFingerprinter,
        now: Callable[[], datetime],
        new_id: Callable[[], UUID],
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        if max_attempts <= 0:
            raise ValueError("max attempts must be positive")
        self._repository = repository
        self._fingerprinter = fingerprinter
        self._now = now
        self._new_id = new_id
        self._max_attempts = max_attempts

    async def __call__(
        self,
        job_id: UUID,
        owner_hash: str,
        idempotency_key: str,
        *,
        quota: UserQuota = DEFAULT_USER_QUOTA,
    ) -> DownloadView:
        owner_hash = validate_owner_hash(owner_hash)
        idempotency_key = validate_idempotency_key(idempotency_key)
        now = validate_now(self._now())
        original = await _owned_job(self._repository, job_id, owner_hash)
        if original.source_kind != DownloadSourceKind.REMOTE_PROVIDER.value:
            raise ApplicationError(ApplicationErrorCode.INVALID_STATE)
        if original.error_code == DownloadErrorCode.CONTEXT_CHANGED.value:
            raise ApplicationError(ApplicationErrorCode.CONTEXT_CHANGED)
        retryable_statuses = {
            DownloadStatus.FAILED.value,
            DownloadStatus.CANCELLED.value,
        }
        if original.status == DownloadStatus.SUCCEEDED.value:
            try:
                artifact = await self._repository.get_artifact(job_id, owner_hash, now)
            except PersistenceNotFound:
                artifact = None
            if artifact is not None:
                raise ApplicationError(ApplicationErrorCode.INVALID_STATE)
        elif original.status not in retryable_statuses:
            raise ApplicationError(ApplicationErrorCode.INVALID_STATE)
        if original.inspection_id is None or original.format_id is None:
            raise ApplicationError(ApplicationErrorCode.NOT_FOUND)

        command = DownloadCreate(
            id=self._new_id(),
            inspection_id=original.inspection_id,
            format_id=original.format_id,
            owner_hash=owner_hash,
            idempotency_key=idempotency_key,
            request_fingerprint=self._fingerprinter.fingerprint(
                "download-retry",
                str(original.id),
                original.request_fingerprint,
            ),
            semantic_plan=dict(original.semantic_plan),
            max_attempts=self._max_attempts,
            allow_expired_source=True,
            quota=quota,
        )
        try:
            saved = await self._repository.create_job(
                command,
                now=now,
            )
        except PersistenceIdempotencyConflict as exc:
            raise ApplicationError(ApplicationErrorCode.IDEMPOTENCY_CONFLICT) from exc
        except PersistenceNotFound as exc:
            raise ApplicationError(ApplicationErrorCode.RESOURCE_EXPIRED) from exc
        except PersistenceConflict as exc:
            raise ApplicationError(ApplicationErrorCode.INTERNAL_ERROR) from exc
        return download_view(saved.job)
