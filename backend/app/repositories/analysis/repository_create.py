"""Atomic analysis job, retention lock and outbox creation."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError

from app.models import AnalysisJobRow
from app.repositories.analysis.repository_base import AnalysisRepositoryBase
from app.repositories.analysis.repository_mapping import analysis_job_snapshot
from app.repositories.analysis.repository_sources import (
    new_source_lock,
    validate_create_source,
)
from app.repositories.analysis.run_factory import new_analysis_run
from app.repositories.quota_admission import lock_admission, reserve
from app.services.analysis.errors import (
    PersistenceConflict,
    PersistenceIdempotencyConflict,
)
from app.services.analysis.models import AnalysisCreate, AnalysisJobSaveResult


class AnalysisCreationRepository(AnalysisRepositoryBase):
    async def create_job_and_enqueue(
        self, command: AnalysisCreate, *, now: datetime
    ) -> AnalysisJobSaveResult:
        if command.outbox_event_type != "analysis.requested":
            raise PersistenceConflict("invalid analysis outbox event type")
        async with self._sessions() as session:
            try:
                async with session.begin():
                    await lock_admission(session, command.owner_hash)
                    existing = await session.scalar(self._key_query(command))
                    if existing is not None:
                        return self._key_replay(existing, command)
                    await validate_create_source(session, command, now)
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
                    row = self._new_row(command, now)
                    session.add(row)
                    # The lock references analysis_jobs. Flush the parent first
                    # instead of relying on SQLAlchemy to infer an ORM dependency
                    # from UUID values alone (there is no relationship configured).
                    await session.flush((row,))
                    run = new_analysis_run(
                        run_id=command.run_id,
                        job_id=row.id,
                        run_no=1,
                        trigger="initial",
                        max_attempts=command.max_attempts,
                        now=now,
                    )
                    session.add(run)
                    lock = new_source_lock(row, now)
                    if lock is not None:
                        session.add(lock)
                    session.add(
                        self.requested_event(
                            row,
                            run,
                            command.outbox_event_id,
                            command.outbox_event_type,
                            now,
                        )
                    )
                    await session.flush()
                    result = AnalysisJobSaveResult(
                        analysis_job_snapshot(row), created=True
                    )
                return result
            except IntegrityError as exc:
                await session.rollback()
                existing = await session.scalar(self._key_query(command))
                if existing is not None:
                    return self._key_replay(existing, command)
                raise exc

    @staticmethod
    def _key_query(command: AnalysisCreate) -> Select[tuple[AnalysisJobRow]]:
        return select(AnalysisJobRow).where(
            AnalysisJobRow.owner_hash == command.owner_hash,
            AnalysisJobRow.idempotency_key == command.idempotency_key,
        )

    @staticmethod
    def _key_replay(
        row: AnalysisJobRow, command: AnalysisCreate
    ) -> AnalysisJobSaveResult:
        if row.request_fingerprint != command.request_fingerprint:
            raise PersistenceIdempotencyConflict("analysis idempotency key reused")
        return AnalysisJobSaveResult(analysis_job_snapshot(row), created=False)

    @staticmethod
    def _new_row(command: AnalysisCreate, now: datetime) -> AnalysisJobRow:
        return AnalysisJobRow(
            id=command.id,
            content_source=None
            if command.content_source is None
            else command.content_source.model_dump(mode="json"),
            input_kind=command.input_kind.value,
            result_contract=command.result_contract.value,
            artifact_id=command.artifact_id,
            document_id=command.document_id,
            owner_hash=command.owner_hash,
            idempotency_key=command.idempotency_key,
            request_fingerprint=command.request_fingerprint,
            input_sha256=command.input_sha256,
            skill_id=command.skill_id,
            skill_instructions=command.skill_instructions,
            skill_instructions_sha256=command.skill_instructions_sha256,
            output_language=command.output_language,
            custom_prompt=command.custom_prompt,
            max_attempts=command.max_attempts,
            active_run_id=command.run_id,
            current_run_no=1,
            current_run_trigger="initial",
            created_at=now,
            updated_at=now,
        )
