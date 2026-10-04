"""Owner-scoped, storage-safe download deletion preparation."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from app.core.db import utc_now
from app.models import (
    AnalysisArtifactLockRow,
    ArtifactRow,
    CreationMaterialRow,
    DownloadJobRow,
    DownloadThumbnailRow,
    MediaImportAttemptRow,
)
from app.models.download_intent import DownloadIntentRow
from app.repositories.errors import RepositoryConflict, RepositoryNotFound
from app.repositories.repository_base import RepositoryBase
from app.services.downloads.download_models import (
    DownloadCleanupRef,
    DownloadDeletionPlan,
)
from app.services.downloads.intent_models import IntentStatus

_ACTIVE_STATUSES = {"queued", "running", "retry_wait"}


class DownloadDeleteRepository(RepositoryBase):
    async def prepare_download_deletion(
        self, job_id: UUID, owner_hash: str, *, now: datetime
    ) -> DownloadDeletionPlan:
        async with self._sessions() as session, session.begin():
            job = await session.scalar(
                select(DownloadJobRow)
                .where(
                    DownloadJobRow.id == job_id,
                    DownloadJobRow.owner_hash == owner_hash,
                )
                .with_for_update()
            )
            if job is None:
                raise RepositoryNotFound("download job does not exist")
            if job.status in _ACTIVE_STATUSES:
                raise RepositoryConflict("active download job must be cancelled")
            artifact = await session.scalar(
                select(ArtifactRow)
                .where(ArtifactRow.job_id == job_id)
                .with_for_update()
            )
            if artifact is not None:
                lock = await session.scalar(
                    select(AnalysisArtifactLockRow.job_id).where(
                        AnalysisArtifactLockRow.artifact_id == artifact.id
                    )
                )
                if lock is not None:
                    raise RepositoryConflict("download is locked by analysis")
                if (
                    await session.scalar(
                        select(CreationMaterialRow.id)
                        .where(
                            CreationMaterialRow.artifact_id == artifact.id,
                            CreationMaterialRow.owner_hash == owner_hash,
                        )
                        .limit(1)
                    )
                    is not None
                ):
                    raise RepositoryConflict(
                        "download is retained as a creation source"
                    )
                artifact.deleted_at = artifact.deleted_at or now
            thumbnail = await session.scalar(
                select(DownloadThumbnailRow)
                .where(DownloadThumbnailRow.job_id == job_id)
                .with_for_update()
            )
            attempts = tuple(
                await session.scalars(
                    select(MediaImportAttemptRow)
                    .where(MediaImportAttemptRow.resource_id == job_id)
                    .order_by(MediaImportAttemptRow.attempt)
                    .with_for_update()
                )
            )
            cleanup = tuple(
                DownloadCleanupRef(item.object_key, item.upload_id) for item in attempts
            )
            if artifact is not None:
                cleanup += (DownloadCleanupRef(artifact.object_key),)
            if thumbnail is not None:
                cleanup += (DownloadCleanupRef(thumbnail.object_key),)
            return DownloadDeletionPlan(
                job_id=job.id,
                owner_hash=job.owner_hash,
                attempt=max((job.attempt, *(item.attempt for item in attempts))),
                cleanup=cleanup,
            )

    async def finish_download_deletion(self, job_id: UUID, owner_hash: str) -> None:
        async with self._sessions() as session, session.begin():
            # Same lock order as handoff/cancel: intent, then the referenced job.
            intent = await session.scalar(
                select(DownloadIntentRow)
                .where(
                    DownloadIntentRow.job_id == job_id,
                    DownloadIntentRow.owner_hash == owner_hash,
                )
                .with_for_update()
            )
            job = await session.scalar(
                select(DownloadJobRow)
                .where(
                    DownloadJobRow.id == job_id,
                    DownloadJobRow.owner_hash == owner_hash,
                )
                .with_for_update()
            )
            if job is None:
                raise RepositoryNotFound("download job does not exist")
            if intent is not None:
                intent.status = IntentStatus.EXPIRED.value
                intent.reason_code = "resource_expired"
                intent.job_id = None
                intent.version += 1
                intent.updated_at = utc_now()
                await session.flush()
            await session.delete(job)
