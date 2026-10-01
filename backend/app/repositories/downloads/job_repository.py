"""Transactional job creation, reads and lease acquisition."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DownloadJobRow, MediaFormatRow, MediaInspectionRow
from app.models.download_intent import DownloadIntentRow
from app.repositories.downloads.events import requested_event
from app.repositories.downloads.mapping import job_snapshot
from app.repositories.errors import (
    IdempotencyConflict,
    RepositoryConflict,
    RepositoryNotFound,
)
from app.repositories.quota_admission import lock_admission, reserve
from app.repositories.repository_base import RepositoryBase
from app.services.downloads.download_models import (
    DownloadCreate,
    JobSaveResult,
    JobSnapshot,
)
from app.services.downloads.intent_models import IntentStatus

_ACTIVE_JOB_STATUSES = ("queued", "running", "retry_wait")


class JobRepository(RepositoryBase):
    async def create_job(
        self, command: DownloadCreate, *, now: datetime
    ) -> JobSaveResult:
        async with self._sessions() as session:
            intent = None
            try:
                async with session.begin():
                    await lock_admission(session, command.owner_hash)
                    # Explicit history retries are separate user-confirmed jobs;
                    # they do not replace the original intent's unique handoff.
                    intent = (
                        None
                        if command.allow_expired_source
                        else await session.scalar(
                            select(DownloadIntentRow)
                            .where(
                                DownloadIntentRow.inspection_id
                                == command.inspection_id,
                                DownloadIntentRow.owner_hash == command.owner_hash,
                            )
                            .with_for_update()
                        )
                    )
                    if intent is not None:
                        if intent.status == IntentStatus.HANDED_OFF.value:
                            handed_off = await session.get(
                                DownloadJobRow, intent.job_id
                            )
                            if handed_off is None:
                                raise RepositoryConflict(
                                    "intent download is unavailable"
                                )
                            return self._idempotent_result(handed_off, command)
                        if intent.status != IntentStatus.READY.value:
                            raise RepositoryConflict("intent is not ready for download")
                    existing = await session.scalar(self._idempotency_query(command))
                    if existing is not None:
                        result = self._idempotent_result(existing, command)
                        _handoff(intent, existing, now)
                        return result
                    active = await session.scalar(self._active_request_query(command))
                    if active is not None:
                        _handoff(intent, active, now)
                        return JobSaveResult(job_snapshot(active), created=False)
                    await self._validate_source(session, command, now)
                    await reserve(
                        session,
                        self._quota_policy,
                        owner_hash=command.owner_hash,
                        resource_id=command.id,
                        kind="download",
                        now=now,
                        quota=command.quota,
                    )
                    row = DownloadJobRow(
                        id=command.id,
                        source_kind=command.source_kind,
                        inspection_id=command.inspection_id,
                        format_id=command.format_id,
                        owner_hash=command.owner_hash,
                        idempotency_key=command.idempotency_key,
                        request_fingerprint=command.request_fingerprint,
                        semantic_plan=command.semantic_plan,
                        max_attempts=command.max_attempts,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(row)
                    session.add(requested_event(row, now))
                    await session.flush()
                    _handoff(intent, row, now)
                    result = JobSaveResult(job_snapshot(row), created=True)
                return result
            except IntegrityError as exc:
                await session.rollback()
                if intent is not None:
                    raise
                existing = await session.scalar(self._idempotency_query(command))
                if existing is not None:
                    try:
                        return self._idempotent_result(existing, command)
                    except IdempotencyConflict as conflict:
                        raise conflict from exc
                active = await session.scalar(self._active_request_query(command))
                if active is not None:
                    return JobSaveResult(job_snapshot(active), created=False)
                raise

    @staticmethod
    def _active_request_query(
        command: DownloadCreate,
    ) -> Select[tuple[DownloadJobRow]]:
        return (
            select(DownloadJobRow)
            .where(
                DownloadJobRow.source_kind == "remote_provider",
                DownloadJobRow.owner_hash == command.owner_hash,
                DownloadJobRow.request_fingerprint == command.request_fingerprint,
                DownloadJobRow.status.in_(_ACTIVE_JOB_STATUSES),
            )
            .order_by(DownloadJobRow.created_at.desc())
            .limit(1)
        )

    async def get_job(self, job_id: UUID) -> JobSnapshot:
        async with self._sessions() as session:
            row = await session.get(DownloadJobRow, job_id)
            if row is None:
                raise RepositoryNotFound("download job does not exist")
            return job_snapshot(row)

    async def claim_job(
        self,
        job_id: UUID,
        worker_id: str,
        now: datetime,
        lease_for: timedelta,
    ) -> JobSnapshot | None:
        statement = (
            update(DownloadJobRow)
            .where(
                DownloadJobRow.id == job_id,
                DownloadJobRow.source_kind == "remote_provider",
                DownloadJobRow.status == "queued",
                DownloadJobRow.attempt < DownloadJobRow.max_attempts,
                DownloadJobRow.retry_at.is_(None),
            )
            .values(
                status="running",
                stage="revalidating",
                stage_rank=1,
                attempt=DownloadJobRow.attempt + 1,
                version=DownloadJobRow.version + 1,
                lease_owner=worker_id,
                lease_expires_at=now + lease_for,
                heartbeat_at=now,
                started_at=func.coalesce(DownloadJobRow.started_at, now),
                retry_at=None,
                error_code=None,
                error_message=None,
                execution_context=None,
                execution_context_attempt=None,
                updated_at=now,
            )
            .returning(DownloadJobRow)
        )
        async with self._sessions() as session, session.begin():
            return_row = (await session.execute(statement)).scalar_one_or_none()
            return None if return_row is None else job_snapshot(return_row)

    @staticmethod
    def _idempotency_query(
        command: DownloadCreate,
    ) -> Select[tuple[DownloadJobRow]]:
        return select(DownloadJobRow).where(
            DownloadJobRow.owner_hash == command.owner_hash,
            DownloadJobRow.idempotency_key == command.idempotency_key,
        )

    @staticmethod
    def _idempotent_result(
        row: DownloadJobRow, command: DownloadCreate
    ) -> JobSaveResult:
        if row.request_fingerprint != command.request_fingerprint:
            raise IdempotencyConflict("download idempotency key already used")
        return JobSaveResult(job_snapshot(row), created=False)

    @staticmethod
    async def _validate_source(
        session: AsyncSession, command: DownloadCreate, now: datetime
    ) -> None:
        if command.source_kind != "remote_provider":
            raise RepositoryConflict("download source kind is not remotely inspectable")
        if command.inspection_id is None or command.format_id is None:
            raise RepositoryConflict("remote download source is incomplete")
        source_filters = [
            MediaInspectionRow.id == command.inspection_id,
            MediaInspectionRow.owner_hash == command.owner_hash,
            MediaFormatRow.id == command.format_id,
        ]
        if not command.allow_expired_source:
            # Explicit retries may reuse an expired snapshot reference. The
            # worker re-inspects the provider before it downloads any bytes.
            source_filters.extend(
                (
                    MediaInspectionRow.expires_at > now,
                    MediaFormatRow.expires_at > now,
                )
            )
        selected = (
            await session.execute(
                select(MediaInspectionRow, MediaFormatRow)
                .join(
                    MediaFormatRow,
                    MediaFormatRow.inspection_id == MediaInspectionRow.id,
                )
                .where(*source_filters)
            )
        ).one_or_none()
        if selected is None:
            raise RepositoryNotFound("inspection or format does not exist or expired")
        _, selected_format = selected
        if selected_format.semantic_plan != command.semantic_plan:
            raise RepositoryConflict("semantic plan differs from selected format")


def _handoff(
    intent: DownloadIntentRow | None, job: DownloadJobRow, now: datetime
) -> None:
    if intent is not None:
        intent.status = IntentStatus.HANDED_OFF.value
        intent.job_id = job.id
        intent.version += 1
        intent.updated_at = now
