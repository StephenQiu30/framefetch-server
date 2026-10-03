"""Atomic same-job manual analysis retry creation."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import as_utc
from app.models import AnalysisJobRow, AnalysisRetryOperationRow, AnalysisRunRow
from app.repositories.analysis.repository_base import AnalysisRepositoryBase
from app.repositories.analysis.repository_mapping import analysis_job_snapshot
from app.repositories.analysis.repository_sources import (
    new_source_lock,
    require_retry_source,
)
from app.repositories.analysis.run_factory import new_analysis_run
from app.repositories.quota_admission import lock_admission, reserve
from app.services.analysis.errors import (
    PersistenceActiveRun,
    PersistenceConflict,
    PersistenceNotFound,
    PersistenceRetryLimited,
)
from app.services.analysis.models import AnalysisJobSaveResult, AnalysisRetry


class AnalysisRetryRepository(AnalysisRepositoryBase):
    async def retry_job_and_enqueue(
        self, command: AnalysisRetry, *, now: datetime
    ) -> AnalysisJobSaveResult:
        async with self._sessions() as session:
            try:
                async with session.begin():
                    await lock_admission(session, command.owner_hash)
                    row = await session.scalar(
                        select(AnalysisJobRow)
                        .where(
                            AnalysisJobRow.id == command.job_id,
                            AnalysisJobRow.owner_hash == command.owner_hash,
                        )
                        .with_for_update()
                    )
                    if row is None:
                        raise PersistenceNotFound("analysis job does not exist")
                    replay = await self._replay(session, row, command)
                    if replay is not None:
                        return replay
                    if row.status not in {"failed", "cancelled", "succeeded"}:
                        raise PersistenceActiveRun("analysis already has an active run")
                    await self._require_retry_capacity(session, row, command, now)
                    await require_retry_source(session, row, now)
                    await reserve(
                        session,
                        self._quota_policy,
                        owner_hash=command.owner_hash,
                        resource_id=command.run_id,
                        kind="analysis",
                        analysis_attempts=command.max_attempts,
                        now=now,
                        quota=command.quota,
                    )
                    run = new_analysis_run(
                        run_id=command.run_id,
                        job_id=row.id,
                        run_no=row.current_run_no + 1,
                        trigger=command.trigger,
                        max_attempts=command.max_attempts,
                        now=now,
                    )
                    session.add(run)
                    # The retry operation references the new run, but the ORM models do
                    # not expose a relationship from which SQLAlchemy can infer insert
                    # ordering. Persist the run before adding dependent rows.
                    await session.flush()
                    lock = new_source_lock(row, now)
                    if lock is not None:
                        session.add(lock)
                    session.add(
                        AnalysisRetryOperationRow(
                            job_id=row.id,
                            run_id=run.id,
                            operation="retry",
                            idempotency_key=command.idempotency_key,
                            created_at=now,
                        )
                    )
                    self._reset_job(row, run, now)
                    session.add(
                        self.requested_event(
                            row,
                            run,
                            command.outbox_event_id,
                            "analysis.requested",
                            now,
                        )
                    )
                    await session.flush()
                    return AnalysisJobSaveResult(
                        analysis_job_snapshot(row, run), created=True
                    )
            except IntegrityError as exc:
                await session.rollback()
                async with session.begin():
                    row = await session.scalar(
                        select(AnalysisJobRow).where(
                            AnalysisJobRow.id == command.job_id,
                            AnalysisJobRow.owner_hash == command.owner_hash,
                        )
                    )
                    if row is None:
                        raise PersistenceNotFound(
                            "analysis job does not exist"
                        ) from exc
                    replay = await self._replay(session, row, command)
                    if replay is None:
                        raise
                    return replay

    @staticmethod
    async def _replay(
        session: AsyncSession, row: AnalysisJobRow, command: AnalysisRetry
    ) -> AnalysisJobSaveResult | None:
        operation = await session.scalar(
            select(AnalysisRetryOperationRow).where(
                AnalysisRetryOperationRow.job_id == row.id,
                AnalysisRetryOperationRow.operation == "retry",
                AnalysisRetryOperationRow.idempotency_key == command.idempotency_key,
            )
        )
        if operation is None:
            return None
        run = await session.get(AnalysisRunRow, operation.run_id)
        if run is None:
            raise PersistenceConflict("retry run is missing")
        return AnalysisJobSaveResult(analysis_job_snapshot(row, run), created=False)

    @staticmethod
    async def _require_retry_capacity(
        session: AsyncSession,
        row: AnalysisJobRow,
        command: AnalysisRetry,
        now: datetime,
    ) -> None:
        if row.current_run_no >= command.max_runs_per_job:
            raise PersistenceRetryLimited("analysis run limit reached")
        current_run = await session.get(AnalysisRunRow, row.active_run_id)
        if (
            current_run is not None
            and command.min_interval_seconds > 0
            and as_utc(current_run.created_at)
            + timedelta(seconds=command.min_interval_seconds)
            > as_utc(now)
        ):
            raise PersistenceRetryLimited("analysis retry interval not elapsed")
        daily_retries = await session.scalar(
            select(func.count())
            .select_from(AnalysisRunRow)
            .join(AnalysisJobRow, AnalysisJobRow.id == AnalysisRunRow.job_id)
            .where(
                AnalysisJobRow.owner_hash == command.owner_hash,
                AnalysisRunRow.trigger.in_({"manual_retry", "manual_rerun"}),
                AnalysisRunRow.created_at >= now - timedelta(days=1),
            )
        )
        if int(daily_retries or 0) >= command.retries_per_day:
            raise PersistenceRetryLimited("owner daily analysis retry limit reached")

    @staticmethod
    def _reset_job(row: AnalysisJobRow, run: AnalysisRunRow, now: datetime) -> None:
        row.active_run_id = run.id
        row.current_run_no = run.run_no
        row.current_run_trigger = run.trigger
        row.status = "queued"
        row.stage = None
        row.stage_rank = 0
        row.progress = 0
        row.attempt = 0
        row.max_attempts = run.max_attempts
        row.version += 1
        row.lease_owner = None
        row.lease_expires_at = None
        row.heartbeat_at = None
        row.started_at = None
        row.retry_at = None
        row.cancel_requested_at = None
        row.finished_at = None
        row.error_code = None
        row.error_message = None
        row.updated_at = now
