from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.repositories.analysis.repository import SqlAlchemyAnalysisRepository
from app.repositories.downloads.repository import SqlAlchemyDownloadRepository
from app.repositories.errors import (
    LeaseConflict,
    RepositoryConflict,
    RepositoryNotFound,
)
from app.services.analysis.errors import PersistenceConflict, PersistenceNotFound
from app.services.analysis.models import AnalysisJobSnapshot, AnalysisPublish
from app.services.analysis.rules.result_types import AnalysisResult
from app.services.analysis_execution.errors import (
    AnalysisOwnershipLost,
    AnalysisPersistenceRejected,
    AnalysisPersistenceUnavailable,
    AnalysisSourceUnavailable,
)
from app.services.analysis_execution.models import (
    AnalysisArtifactSource,
    AnalysisScreenplaySource,
    AnalysisStepBegin,
)


class AnalysisExecutionPersistence:
    def __init__(
        self,
        analysis: SqlAlchemyAnalysisRepository,
        downloads: SqlAlchemyDownloadRepository,
    ) -> None:
        self._analysis = analysis
        self._downloads = downloads

    async def claim_run(
        self,
        job_id: UUID,
        run_id: UUID,
        run_no: int,
        owner: str,
        now: datetime,
        lease_for: timedelta,
    ) -> AnalysisJobSnapshot | None:
        with _translate_errors():
            return await self._analysis.claim_run(
                job_id, run_id, run_no, owner, now, lease_for
            )
        raise AssertionError("unreachable")

    async def get_job(self, job_id: UUID) -> AnalysisJobSnapshot | None:
        with _translate_errors():
            return await self._analysis.get_job(job_id)
        raise AssertionError("unreachable")

    async def get_artifact_source(
        self, job: AnalysisJobSnapshot, now: datetime
    ) -> AnalysisArtifactSource:
        with _translate_errors():
            if job.artifact_id is None:
                raise AnalysisSourceUnavailable
            projection = await self._analysis.get_artifact(job.artifact_id)
            if (
                projection is None
                or projection.owner_hash != job.owner_hash
                or projection.download_status != "succeeded"
                or projection.sha256 != job.input_sha256
            ):
                raise AnalysisSourceUnavailable
            artifact = await self._downloads.get_artifact(
                projection.download_id, projection.owner_hash, now
            )
            if artifact.id != projection.id or artifact.sha256 != job.input_sha256:
                raise AnalysisSourceUnavailable
            return AnalysisArtifactSource(
                artifact_id=artifact.id,
                bucket=artifact.bucket,
                object_key=artifact.object_key,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
                duration_ms=artifact.duration_ms,
                container=artifact.container,
            )
        raise AssertionError("unreachable")

    async def get_screenplay_source(
        self, job: AnalysisJobSnapshot, now: datetime
    ) -> AnalysisScreenplaySource:
        with _translate_errors():
            if job.document_id is None or job.artifact_id is not None:
                raise AnalysisSourceUnavailable
            try:
                source = await self._analysis.get_screenplay_source(
                    job.document_id, now
                )
            except (TypeError, ValueError) as exc:
                raise AnalysisSourceUnavailable from exc
            if (
                source is None
                or source.document_id != job.document_id
                or source.owner_hash != job.owner_hash
                or source.sha256 != job.input_sha256
            ):
                raise AnalysisSourceUnavailable
            return source
        raise AssertionError("unreachable")

    async def heartbeat(
        self,
        job_id: UUID,
        worker_id: str,
        attempt: int,
        *,
        stage: str,
        progress: int,
        now: datetime,
        lease_for: timedelta,
    ) -> bool:
        with _translate_errors():
            return await self._analysis.heartbeat(
                job_id,
                worker_id,
                attempt,
                stage=stage,
                progress=progress,
                now=now,
                lease_for=lease_for,
            )
        raise AssertionError("unreachable")

    async def publish_result(
        self,
        job_id: UUID,
        run_id: UUID,
        worker_id: str,
        expected_version: int,
        result: AnalysisResult,
        provider: str,
        model: str,
        cli_version: str,
        now: datetime,
    ) -> None:
        with _translate_errors():
            await self._analysis.publish_result(
                AnalysisPublish(
                    job_id=job_id,
                    run_id=run_id,
                    result=result,
                    lease_owner=worker_id,
                    expected_version=expected_version,
                    provider=provider,
                    model=model,
                    cli_version=cli_version,
                    now=now,
                )
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
    ) -> AnalysisJobSnapshot:
        with _translate_errors():
            return await self._analysis.complete_failure(
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

    async def fail_run(
        self, job_id: UUID, run_id: UUID, *, error_code: str, now: datetime
    ) -> AnalysisJobSnapshot | None:
        with _translate_errors():
            return await self._analysis.fail_run(
                job_id, run_id, error_code=error_code, now=now
            )
        raise AssertionError("unreachable")

    async def begin_step(
        self, run_id: UUID, step_key: str, input_sha256: str, *, now: datetime
    ) -> AnalysisStepBegin:
        with _translate_errors():
            return await self._analysis.begin_step(
                run_id, step_key, input_sha256, now=now
            )
        raise AssertionError("unreachable")

    async def complete_step(
        self, run_id: UUID, step_key: str, payload: object, *, now: datetime
    ) -> None:
        with _translate_errors():
            await self._analysis.complete_step(run_id, step_key, payload, now=now)

    async def abandon_step(self, run_id: UUID, step_key: str) -> None:
        with _translate_errors():
            await self._analysis.abandon_step(run_id, step_key)

    async def fail_step(
        self, run_id: UUID, step_key: str, error_code: str, *, now: datetime
    ) -> None:
        with _translate_errors():
            await self._analysis.fail_step(run_id, step_key, error_code, now=now)

    async def has_started_step(self, run_id: UUID) -> bool:
        with _translate_errors():
            return await self._analysis.has_started_step(run_id)
        raise AssertionError("unreachable")

    async def purge_steps(self, run_id: UUID) -> None:
        with _translate_errors():
            await self._analysis.purge_steps(run_id)


@contextmanager
def _translate_errors() -> Iterator[None]:
    try:
        yield
    except (
        AnalysisOwnershipLost,
        AnalysisPersistenceRejected,
        AnalysisPersistenceUnavailable,
        AnalysisSourceUnavailable,
    ):
        raise
    except (PersistenceNotFound, RepositoryNotFound) as exc:
        raise AnalysisSourceUnavailable from exc
    except (PersistenceConflict, LeaseConflict, RepositoryConflict) as exc:
        raise AnalysisOwnershipLost from exc
    except IntegrityError as exc:
        raise AnalysisPersistenceRejected from exc
    except Exception as exc:
        raise AnalysisPersistenceUnavailable from exc
