"""Atomic terminal transitions and deterministic artifact persistence."""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.db import as_utc
from app.models import ArtifactRow, DownloadJobRow
from app.repositories.contracts import ArtifactCreate
from app.repositories.downloads.mapping import artifact_snapshot, job_snapshot
from app.repositories.errors import (
    LeaseConflict,
    RepositoryConflict,
    RepositoryNotFound,
)
from app.repositories.quota_admission import lock_admission
from app.repositories.repository_base import RepositoryBase
from app.repositories.watermark import enqueue_automatic
from app.services.downloads.download_models import ArtifactSnapshot, JobSnapshot
from app.services.downloads.rules.artifact_keys import build_artifact_object_key


def _validate_artifact(artifact: ArtifactCreate) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", artifact.sha256) is None:
        raise ValueError("sha256 must be lowercase hexadecimal")
    if artifact.size_bytes <= 0 or artifact.duration_ms <= 0:
        raise ValueError("artifact size and duration must be positive")


class CompletionRepository(RepositoryBase):
    async def complete_success(
        self,
        job_id: UUID,
        worker_id: str,
        attempt: int,
        artifact: ArtifactCreate,
        *,
        now: datetime,
    ) -> ArtifactSnapshot:
        _validate_artifact(artifact)
        object_key = build_artifact_object_key(job_id, attempt, artifact.container)
        async with self._sessions() as session, session.begin():
            owner = await session.scalar(
                select(DownloadJobRow.owner_hash).where(DownloadJobRow.id == job_id)
            )
            if owner is not None:
                await lock_admission(session, owner)
            row = await session.scalar(
                select(DownloadJobRow)
                .where(DownloadJobRow.id == job_id)
                .with_for_update()
            )
            if row is None:
                raise RepositoryNotFound("download job does not exist")
            if row.status == "succeeded":
                stored = await session.scalar(
                    select(ArtifactRow).where(ArtifactRow.job_id == job_id)
                )
                if stored is None or (
                    stored.object_key != object_key
                    or stored.bucket != artifact.bucket
                    or stored.sha256 != artifact.sha256
                    or stored.size_bytes != artifact.size_bytes
                    or stored.duration_ms != artifact.duration_ms
                ):
                    raise RepositoryConflict("artifact completion is inconsistent")
                return artifact_snapshot(stored)
            self._require_lease(row, worker_id, attempt, now)
            if row.stage != "uploading":
                raise LeaseConflict("job has not completed the upload stage")
            stored = ArtifactRow(
                id=uuid4(),
                job_id=job_id,
                attempt=attempt,
                bucket=artifact.bucket,
                object_key=object_key,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
                duration_ms=artifact.duration_ms,
                container=artifact.container.lower(),
                content_type=artifact.content_type,
                media_metadata=artifact.media_metadata,
                created_at=now,
            )
            session.add(stored)
            row.status = "succeeded"
            row.stage = None
            row.stage_rank = 0
            row.progress = 100
            row.version += 1
            row.finished_at = now
            row.lease_owner = None
            row.lease_expires_at = None
            row.heartbeat_at = now
            row.updated_at = now
            await session.flush()
            await enqueue_automatic(session, row, stored, self._quota_policy)
            return artifact_snapshot(stored)

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
        retry_at: datetime | None = None,
    ) -> JobSnapshot:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(DownloadJobRow)
                .where(DownloadJobRow.id == job_id)
                .with_for_update()
            )
            if row is None:
                raise RepositoryNotFound("download job does not exist")
            self._require_lease(row, worker_id, attempt, now)
            should_retry = retryable and row.attempt < row.max_attempts
            if should_retry and (retry_at is None or as_utc(retry_at) <= as_utc(now)):
                raise ValueError("retry_at must be in the future")
            row.status = "retry_wait" if should_retry else "failed"
            row.stage = None
            row.stage_rank = 0
            row.version += 1
            row.retry_at = retry_at if should_retry else None
            row.finished_at = None if should_retry else now
            row.error_code = error_code
            row.error_message = error_message[:512]
            row.lease_owner = None
            row.lease_expires_at = None
            row.updated_at = now
            await session.flush()
            return job_snapshot(row)

    @staticmethod
    def _require_lease(
        row: DownloadJobRow, worker_id: str, attempt: int, now: datetime
    ) -> None:
        if (
            row.status != "running"
            or row.lease_owner != worker_id
            or row.attempt != attempt
            or row.lease_expires_at is None
            or as_utc(row.lease_expires_at) <= as_utc(now)
        ):
            raise LeaseConflict("worker no longer owns this job attempt")
