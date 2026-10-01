from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from uuid import UUID

from app.repositories.contracts import ArtifactCreate, JobSourceSnapshot
from app.repositories.downloads.repository import SqlAlchemyDownloadRepository
from app.repositories.errors import (
    LeaseConflict,
    RepositoryConflict,
    RepositoryNotFound,
)
from app.services.download_execution.errors import (
    ExecutionOwnershipLost,
    ExecutionPersistenceUnavailable,
    ExecutionSourceUnavailable,
)
from app.services.download_execution.models import ArtifactDetails
from app.services.downloads.download_models import JobSnapshot
from app.services.provider_types import ExecutionContext


class DownloadExecutionRepository:
    def __init__(self, repository: SqlAlchemyDownloadRepository) -> None:
        self._repository = repository

    async def claim_job(
        self, job_id: UUID, worker_id: str, now: datetime, lease_for: timedelta
    ) -> JobSnapshot | None:
        with _translate_errors():
            return await self._repository.claim_job(job_id, worker_id, now, lease_for)
        raise AssertionError("unreachable")

    async def get_job(self, job_id: UUID) -> JobSnapshot:
        with _translate_errors():
            return await self._repository.get_job(job_id)
        raise AssertionError("unreachable")

    async def get_job_source(
        self, job_id: UUID, worker_id: str, attempt: int, now: datetime
    ) -> JobSourceSnapshot:
        with _translate_errors():
            return await self._repository.get_job_source(
                job_id, worker_id, attempt, now
            )
        raise AssertionError("unreachable")

    async def heartbeat(
        self,
        job_id: UUID,
        worker_id: str,
        attempt: int,
        *,
        stage: str,
        stage_rank: int,
        progress: int,
        now: datetime,
        lease_for: timedelta,
    ) -> bool:
        with _translate_errors():
            return await self._repository.heartbeat(
                job_id,
                worker_id,
                attempt,
                stage=stage,
                stage_rank=stage_rank,
                progress=progress,
                now=now,
                lease_for=lease_for,
            )
        raise AssertionError("unreachable")

    async def record_execution_context(
        self,
        job_id: UUID,
        worker_id: str,
        attempt: int,
        context: ExecutionContext,
        now: datetime,
    ) -> None:
        with _translate_errors():
            await self._repository.record_execution_context(
                job_id, worker_id, attempt, context, now
            )

    async def complete_success(
        self,
        job_id: UUID,
        worker_id: str,
        attempt: int,
        artifact: ArtifactDetails,
        *,
        now: datetime,
    ) -> None:
        with _translate_errors():
            await self._repository.complete_success(
                job_id,
                worker_id,
                attempt,
                ArtifactCreate(
                    bucket=artifact.bucket,
                    sha256=artifact.sha256,
                    size_bytes=artifact.size_bytes,
                    duration_ms=artifact.duration_ms,
                    container=artifact.container,
                    content_type=artifact.content_type,
                    media_metadata=artifact.media_metadata,
                ),
                now=now,
            )

    async def complete_failure(
        self,
        job_id: UUID,
        worker_id: str,
        attempt: int,
        *,
        error_code: str,
        error_message: str,
        retryable: bool,
        now: datetime,
        retry_at: datetime | None,
    ) -> JobSnapshot:
        with _translate_errors():
            return await self._repository.complete_failure(
                job_id,
                worker_id,
                attempt,
                error_code=error_code,
                error_message=error_message,
                retryable=retryable,
                now=now,
                retry_at=retry_at,
            )
        raise AssertionError("unreachable")


@contextmanager
def _translate_errors() -> Iterator[None]:
    try:
        yield
    except RepositoryNotFound as exc:
        raise ExecutionSourceUnavailable from exc
    except (LeaseConflict, RepositoryConflict) as exc:
        raise ExecutionOwnershipLost from exc
    except (ExecutionOwnershipLost, ExecutionSourceUnavailable):
        raise
    except Exception as exc:
        raise ExecutionPersistenceUnavailable from exc
