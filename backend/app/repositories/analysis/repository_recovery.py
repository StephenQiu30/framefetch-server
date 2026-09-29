"""Workflow-driven retry and terminal analysis failure transitions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from app.core.db import as_utc
from app.models import AnalysisJobRow
from app.repositories.analysis.repository_base import AnalysisRepositoryBase
from app.repositories.analysis.repository_mapping import analysis_job_snapshot
from app.services.analysis.errors import PersistenceNotFound
from app.services.analysis.models import AnalysisJobSnapshot


class AnalysisRecoveryRepository(AnalysisRepositoryBase):
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
    ) -> AnalysisJobSnapshot:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(AnalysisJobRow)
                .where(AnalysisJobRow.id == job_id)
                .with_for_update()
            )
            if row is None:
                raise PersistenceNotFound("analysis job does not exist")
            run = await self.active_run(session, row, for_update=True)
            self.require_lease(row, worker_id, attempt, now)
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
            row.heartbeat_at = None
            row.updated_at = now
            self.sync_run(row, run)
            if not should_retry:
                await self.release_lock(session, row.id)
            await session.flush()
            return analysis_job_snapshot(row)

    async def fail_run(
        self, job_id: UUID, run_id: UUID, *, error_code: str, now: datetime
    ) -> AnalysisJobSnapshot | None:
        """Close a run whose Workflow can no longer execute it."""
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(AnalysisJobRow)
                .where(AnalysisJobRow.id == job_id)
                .with_for_update()
            )
            if row is None:
                return None
            if row.active_run_id != run_id or row.status not in {
                "queued",
                "running",
                "retry_wait",
            }:
                return analysis_job_snapshot(row)
            run = await self.active_run(session, row, for_update=True)
            row.status = "failed"
            row.stage = None
            row.stage_rank = 0
            row.version += 1
            row.retry_at = None
            row.finished_at = now
            row.error_code = error_code
            row.error_message = error_code
            row.lease_owner = None
            row.lease_expires_at = None
            row.heartbeat_at = None
            row.updated_at = now
            self.sync_run(row, run)
            await self.release_lock(session, row.id)
            await session.flush()
            return analysis_job_snapshot(row)
