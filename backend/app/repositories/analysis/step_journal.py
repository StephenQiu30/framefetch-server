"""Per-run model-call journal backing SkillWorkflow resume."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, exists, select
from sqlalchemy.dialects.postgresql import insert

from app.models import AnalysisStepResultRow
from app.repositories.repository_base import RepositoryBase
from app.services.analysis_execution.errors import AnalysisPersistenceRejected
from app.services.analysis_execution.models import (
    AnalysisStepBegin,
    AnalysisStepStatus,
)

_STARTED = "started"
_SUCCEEDED = "succeeded"


class AnalysisStepJournalRepository(RepositoryBase):
    async def begin_step(
        self, run_id: UUID, step_key: str, input_sha256: str, *, now: datetime
    ) -> AnalysisStepBegin:
        async with self._sessions() as session, session.begin():
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
        self, run_id: UUID, step_key: str, payload: object, *, now: datetime
    ) -> None:
        async with self._sessions() as session, session.begin():
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

    async def abandon_step(self, run_id: UUID, step_key: str) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                delete(AnalysisStepResultRow).where(
                    AnalysisStepResultRow.run_id == run_id,
                    AnalysisStepResultRow.step_key == step_key,
                    AnalysisStepResultRow.status == _STARTED,
                )
            )

    async def fail_step(
        self, run_id: UUID, step_key: str, error_code: str, *, now: datetime
    ) -> None:
        if error_code not in {"invalid_model_output", "analysis_resource_limit"}:
            raise AnalysisPersistenceRejected("unsupported known model failure")
        async with self._sessions() as session, session.begin():
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
