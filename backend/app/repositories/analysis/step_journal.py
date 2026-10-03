"""Per-run model-call journal backing SkillWorkflow resume."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import as_utc
from app.models import AnalysisJobRow, AnalysisRunRow, AnalysisStepResultRow
from app.repositories.repository_base import RepositoryBase
from app.services.analysis_execution.errors import (
    AnalysisExecutionError,
    AnalysisOwnershipLost,
    AnalysisPersistenceRejected,
)
from app.services.analysis_execution.models import (
    AnalysisStepBegin,
    AnalysisStepStatus,
)

_STARTED = "started"
_SUCCEEDED = "succeeded"


class AnalysisStepJournalRepository(RepositoryBase):
    async def begin_step(
        self,
        run_id: UUID,
        step_key: str,
        input_sha256: str,
        *,
        now: datetime,
        owner: str | None = None,
        attempt: int | None = None,
    ) -> AnalysisStepBegin:
        async with self._sessions() as session, session.begin():
            run = await _owned_run(session, run_id, owner, attempt, now)
            existing = await session.get(AnalysisStepResultRow, (run_id, step_key))
            if existing is None and run.execution_binding is not None:
                maximum = run.execution_binding["max_model_calls"]
                if (
                    run.execution_deadline is None
                    or as_utc(now) >= as_utc(run.execution_deadline)
                    or run.model_calls_used >= maximum
                ):
                    raise AnalysisExecutionError("analysis_resource_limit")
            inserted = await session.scalar(
                insert(AnalysisStepResultRow)
                .values(
                    run_id=run_id,
                    step_key=step_key,
                    input_sha256=input_sha256,
                    status=_STARTED,
                    started_at=now,
                )
                .on_conflict_do_nothing()
                .returning(AnalysisStepResultRow.step_key)
            )
            if inserted is not None:
                run.model_calls_used += 1
                return AnalysisStepBegin(AnalysisStepStatus.NEW)
            row = await session.scalar(
                select(AnalysisStepResultRow)
                .where(
                    AnalysisStepResultRow.run_id == run_id,
                    AnalysisStepResultRow.step_key == step_key,
                )
                .with_for_update()
            )
            if row is None:
                raise RuntimeError("analysis step journal row disappeared")
            if row.status == _SUCCEEDED and row.input_sha256 == input_sha256:
                payload = row.payload or {}
                return AnalysisStepBegin(AnalysisStepStatus.REPLAY, payload["value"])
            if row.input_sha256 != input_sha256:
                raise AnalysisPersistenceRejected("analysis step input changed")
            if row.status == "failed":
                return AnalysisStepBegin(
                    AnalysisStepStatus.FAILED, (row.payload or {})["error_code"]
                )
            return AnalysisStepBegin(AnalysisStepStatus.UNKNOWN)

    async def complete_step(
        self,
        run_id: UUID,
        step_key: str,
        payload: object,
        *,
        now: datetime,
        owner: str | None = None,
        attempt: int | None = None,
    ) -> None:
        async with self._sessions() as session, session.begin():
            await _owned_run(session, run_id, owner, attempt, now)
            row = await session.scalar(
                select(AnalysisStepResultRow)
                .where(
                    AnalysisStepResultRow.run_id == run_id,
                    AnalysisStepResultRow.step_key == step_key,
                    AnalysisStepResultRow.status == _STARTED,
                )
                .with_for_update()
            )
            if row is None:
                raise RuntimeError("analysis step is not awaiting a result")
            row.status = _SUCCEEDED
            row.payload = {"value": payload}
            row.completed_at = now

    async def abandon_step(
        self,
        run_id: UUID,
        step_key: str,
        *,
        now: datetime | None = None,
        owner: str | None = None,
        attempt: int | None = None,
    ) -> None:
        async with self._sessions() as session, session.begin():
            run = await _owned_run(session, run_id, owner, attempt, now)
            removed = await session.scalar(
                delete(AnalysisStepResultRow)
                .where(
                    AnalysisStepResultRow.run_id == run_id,
                    AnalysisStepResultRow.step_key == step_key,
                    AnalysisStepResultRow.status == _STARTED,
                )
                .returning(AnalysisStepResultRow.step_key)
            )
            if removed is not None:
                # Existing unbound runs predate the persisted call counter.
                run.model_calls_used = max(0, run.model_calls_used - 1)

    async def fail_step(
        self,
        run_id: UUID,
        step_key: str,
        error_code: str,
        *,
        now: datetime,
        owner: str | None = None,
        attempt: int | None = None,
    ) -> None:
        if error_code not in {"invalid_model_output", "analysis_resource_limit"}:
            raise AnalysisPersistenceRejected("unsupported known model failure")
        async with self._sessions() as session, session.begin():
            await _owned_run(session, run_id, owner, attempt, now)
            row = await session.scalar(
                select(AnalysisStepResultRow)
                .where(
                    AnalysisStepResultRow.run_id == run_id,
                    AnalysisStepResultRow.step_key == step_key,
                    AnalysisStepResultRow.status == _STARTED,
                )
                .with_for_update()
            )
            if row is None:
                raise AnalysisPersistenceRejected(
                    "analysis step is not awaiting a result"
                )
            row.status = "failed"
            row.payload = {"error_code": error_code}
            row.completed_at = now

    async def bind_execution(
        self,
        run_id: UUID,
        binding: dict[str, object],
        *,
        owner: str,
        attempt: int,
        now: datetime,
        deadline: datetime,
    ) -> None:
        maximum = binding.get("max_model_calls")
        if (
            type(maximum) is not int
            or not 1 <= maximum <= 1_024
            or as_utc(deadline) <= as_utc(now)
        ):
            raise AnalysisPersistenceRejected("invalid model execution budget")
        async with self._sessions() as session, session.begin():
            run = await _owned_run(session, run_id, owner, attempt, now)
            if run.execution_binding is not None:
                if run.execution_binding != binding:
                    raise AnalysisExecutionError("analysis_configuration_changed")
                return
            if run.model_calls_used:
                raise AnalysisPersistenceRejected("cannot freeze a started run")
            run.execution_binding = binding
            run.execution_deadline = deadline

    async def has_started_step(self, run_id: UUID) -> bool:
        async with self._sessions() as session:
            return bool(
                await session.scalar(
                    select(
                        exists().where(
                            AnalysisStepResultRow.run_id == run_id,
                            AnalysisStepResultRow.status == _STARTED,
                        )
                    )
                )
            )

    async def purge_steps(self, run_id: UUID) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                delete(AnalysisStepResultRow).where(
                    AnalysisStepResultRow.run_id == run_id
                )
            )


async def _owned_run(
    session: AsyncSession,
    run_id: UUID,
    owner: str | None,
    attempt: int | None,
    now: datetime | None,
) -> AnalysisRunRow:
    if owner is not None:
        job = await session.scalar(
            select(AnalysisJobRow)
            .where(AnalysisJobRow.active_run_id == run_id)
            .with_for_update()
        )
        if (
            job is None
            or job.status != "running"
            or job.deleted_at is not None
            or job.cancel_requested_at is not None
            or job.lease_owner != owner
            or job.attempt != attempt
            or job.lease_expires_at is None
            or now is None
            or as_utc(job.lease_expires_at) <= as_utc(now)
        ):
            raise AnalysisOwnershipLost("analysis step ownership lost")
    run = await session.get(AnalysisRunRow, run_id, with_for_update=True)
    if run is None:
        raise AnalysisPersistenceRejected("analysis run is unavailable")
    return run
