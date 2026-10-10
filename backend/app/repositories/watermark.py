"""Owner-scoped processing admission and fenced output publication."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import Text, cast, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import as_utc, utc_now
from app.models import ArtifactRow, DownloadJobRow, OutboxEventRow, UserRow
from app.models.watermark import WatermarkTaskRow, WatermarkWorkerRow
from app.repositories.auth.mapping import current_user_from_row
from app.repositories.quota_admission import lock_admission, reserve
from app.repositories.repository_base import RepositoryBase
from app.schemas.watermark import (
    WatermarkListResponse,
    WatermarkTaskResponse,
)
from app.services.downloads.errors import ApplicationError
from app.services.downloads.errors import ApplicationErrorCode as Code
from app.services.quotas import (
    DEFAULT_USER_QUOTA,
    QuotaExceeded,
    QuotaPolicy,
    UserQuota,
)

ENGINE = "rapidocr-v4-sttn-e109b9dd"
MAX_OUTPUT_BYTES = 2 * 1024**3


def enqueue(task: WatermarkTaskRow) -> OutboxEventRow:
    return OutboxEventRow(
        aggregate_type="watermark",
        aggregate_id=task.id,
        aggregate_version=task.attempt,
        event_type="watermark.requested",
        payload={"task_id": str(task.id)},
        available_at=utc_now(),
    )


async def enqueue_automatic(
    session: AsyncSession, job: DownloadJobRow, source: ArtifactRow, policy: QuotaPolicy
) -> None:
    """Called with the owner lock in the original file completion transaction.

    A processing admission failure must never roll back a verified original.
    """
    if not source.content_type.startswith("video/"):
        return
    user = await session.scalar(
        select(UserRow).where(
            func.encode(
                func.sha256(func.convert_to(cast(UserRow.id, Text), "UTF8")), "hex"
            )
            == job.owner_hash
        )
    )
    quota = current_user_from_row(user).admission_quota if user else DEFAULT_USER_QUOTA
    task = WatermarkTaskRow(
        id=uuid4(),
        job_id=job.id,
        source_id=source.id,
        source_sha256=source.sha256,
        owner_hash=job.owner_hash,
        idempotency_key=f"automatic:{source.id}",
        engine=ENGINE,
        parameters={},
        status="queued",
        attempt=0,
        size_bytes=0,
    )
    if source.duration_ms > 180_000 or source.size_bytes > MAX_OUTPUT_BYTES:
        task.status, task.error_code = "failed", "unsupported_media"
    else:
        try:
            async with session.begin_nested():
                await reserve(
                    session,
                    policy,
                    owner_hash=job.owner_hash,
                    resource_id=task.id,
                    kind="watermark",
                    now=utc_now(),
                    size_bytes=MAX_OUTPUT_BYTES,
                    quota=quota,
                )
        except QuotaExceeded as exc:
            task.status, task.error_code = "failed", str(exc.code)
    session.add(task)
    if task.status == "queued":
        session.add(enqueue(task))
    await session.flush()


class WatermarkRepository(RepositoryBase):
    async def available(self) -> bool:
        async with self._sessions() as session:
            return bool(
                await session.scalar(
                    select(func.count())
                    .select_from(WatermarkWorkerRow)
                    .where(
                        WatermarkWorkerRow.engine == ENGINE,
                        WatermarkWorkerRow.heartbeat_at
                        > utc_now() - timedelta(seconds=90),
                    )
                )
            )

    async def for_job(self, job_id: UUID, owner: str) -> WatermarkListResponse:
        async with self._sessions() as session:
            if (
                await session.scalar(
                    select(DownloadJobRow.id).where(
                        DownloadJobRow.id == job_id, DownloadJobRow.owner_hash == owner
                    )
                )
                is None
            ):
                raise ApplicationError(Code.NOT_FOUND)
            rows = (
                await session.scalars(
                    select(WatermarkTaskRow)
                    .where(
                        WatermarkTaskRow.job_id == job_id,
                        WatermarkTaskRow.owner_hash == owner,
                    )
                    .order_by(WatermarkTaskRow.created_at.desc())
                )
            ).all()
            items = [WatermarkTaskResponse.model_validate(row) for row in rows]
        return WatermarkListResponse(available=await self.available(), items=items)

    async def create(
        self,
        job_id: UUID,
        owner: str,
        key: str,
        quota: UserQuota,
    ) -> WatermarkTaskResponse:
        async with self._sessions() as session, session.begin():
            await lock_admission(session, owner)
            replay = await session.scalar(
                select(WatermarkTaskRow).where(
                    WatermarkTaskRow.owner_hash == owner,
                    WatermarkTaskRow.idempotency_key == key,
                )
            )
            if replay is not None:
                if replay.job_id != job_id:
                    raise ApplicationError(Code.IDEMPOTENCY_CONFLICT)
                return WatermarkTaskResponse.model_validate(replay)
            job = await session.scalar(
                select(DownloadJobRow)
                .where(DownloadJobRow.id == job_id, DownloadJobRow.owner_hash == owner)
                .with_for_update()
            )
            if job is None:
                raise ApplicationError(Code.NOT_FOUND)
            source = await session.scalar(
                select(ArtifactRow)
                .where(ArtifactRow.job_id == job_id, ArtifactRow.deleted_at.is_(None))
                .with_for_update()
            )
            if job.status != "succeeded" or source is None:
                raise ApplicationError(Code.DOWNLOAD_NOT_READY)
            if (
                source.container not in {"mp4", "webm"}
                or source.duration_ms > 180_000
                or source.size_bytes > MAX_OUTPUT_BYTES
            ):
                raise ApplicationError(Code.INVALID_REQUEST)
            if (
                await session.scalar(
                    select(WatermarkTaskRow.id).where(
                        WatermarkTaskRow.job_id == job_id,
                        WatermarkTaskRow.status.in_(["queued", "running"]),
                    )
                )
                is not None
            ):
                raise ApplicationError(Code.INVALID_STATE)
            if not await self.available():
                raise ApplicationError(Code.RUNTIME_UNAVAILABLE)
            task_id = uuid4()
            await reserve(
                session,
                self._quota_policy,
                owner_hash=owner,
                resource_id=task_id,
                kind="watermark",
                now=utc_now(),
                size_bytes=MAX_OUTPUT_BYTES,
                quota=quota,
            )
            row = WatermarkTaskRow(
                id=task_id,
                job_id=job_id,
                source_id=source.id,
                source_sha256=source.sha256,
                engine=ENGINE,
                owner_hash=owner,
                idempotency_key=key,
                parameters={},
                status="queued",
                attempt=0,
                size_bytes=0,
            )
            session.add(row)
            session.add(enqueue(row))
            await session.flush()
            return WatermarkTaskResponse.model_validate(row)

    async def cancel(self, task_id: UUID, owner: str) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(WatermarkTaskRow)
                .where(
                    WatermarkTaskRow.id == task_id, WatermarkTaskRow.owner_hash == owner
                )
                .with_for_update()
            )
            if row is None:
                raise ApplicationError(Code.NOT_FOUND)
            if row.status in {"queued", "running"}:
                row.status = "cancelled"
                row.updated_at = utc_now()

    async def artifact(
        self, task_id: UUID, owner: str
    ) -> tuple[WatermarkTaskRow, ArtifactRow]:
        async with self._sessions() as session:
            row = await session.scalar(
                select(WatermarkTaskRow).where(
                    WatermarkTaskRow.id == task_id, WatermarkTaskRow.owner_hash == owner
                )
            )
            if row is None:
                raise ApplicationError(Code.NOT_FOUND)
            source = await session.get(ArtifactRow, row.source_id)
            if (
                row.status != "succeeded"
                or row.object_key is None
                or source is None
                or source.deleted_at is not None
            ):
                raise ApplicationError(Code.DOWNLOAD_NOT_READY)
            return row, source

    async def heartbeat_worker(self, worker: str) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                insert(WatermarkWorkerRow)
                .values(id=worker, heartbeat_at=utc_now(), engine=ENGINE)
                .on_conflict_do_update(
                    index_elements=["id"],
                    set_={"heartbeat_at": utc_now(), "engine": ENGINE},
                )
            )

    async def claim(
        self, task_id: UUID, worker: str
    ) -> tuple[WatermarkTaskRow, ArtifactRow] | None:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(WatermarkTaskRow)
                .where(WatermarkTaskRow.id == task_id)
                .with_for_update()
            )
            if row is None or row.status != "queued":
                return None
            source = await session.get(ArtifactRow, row.source_id)
            if (
                source is None
                or row.engine != ENGINE
                or source.deleted_at is not None
                or source.sha256 != row.source_sha256
            ):
                row.status = "failed"
                row.error_code = "source_unavailable"
                return None
            row.status = "running"
            row.attempt += 1
            row.lease_owner = worker
            row.lease_expires_at = utc_now() + timedelta(seconds=120)
            row.updated_at = utc_now()
            row.object_key = f"watermarks/{row.job_id}/{row.id}/{row.attempt}/video.mp4"
            await session.flush()
            return row, source

    async def heartbeat_task(self, task_id: UUID, worker: str, attempt: int) -> bool:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(WatermarkTaskRow)
                .where(WatermarkTaskRow.id == task_id)
                .with_for_update()
            )
            if (
                row is None
                or row.status != "running"
                or row.lease_owner != worker
                or row.attempt != attempt
                or row.lease_expires_at is None
                or as_utc(row.lease_expires_at) <= utc_now()
            ):
                return False
            row.lease_expires_at = utc_now() + timedelta(seconds=120)
            row.updated_at = utc_now()
            return True

    async def finish(
        self,
        task_id: UUID,
        worker: str,
        attempt: int,
        *,
        size: int = 0,
        sha256: str | None = None,
        error: str | None = None,
        unchanged: bool = False,
    ) -> bool:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(WatermarkTaskRow)
                .where(WatermarkTaskRow.id == task_id)
                .with_for_update()
            )
            if (
                row is None
                or row.status != "running"
                or row.lease_owner != worker
                or row.attempt != attempt
                or row.lease_expires_at is None
                or as_utc(row.lease_expires_at) <= utc_now()
            ):
                return False
            source = await session.get(ArtifactRow, row.source_id)
            if source is None or source.deleted_at is not None:
                return False
            row.status = (
                "failed" if error else "unchanged" if unchanged else "succeeded"
            )
            if unchanged:
                row.object_key = None
            row.error_code = error
            row.size_bytes = size
            row.sha256 = sha256
            if not error:
                row.lease_owner = None
                row.lease_expires_at = None
            row.updated_at = utc_now()
            return True

    async def recover(self) -> list[str]:
        cleanup = []
        async with self._sessions() as session, session.begin():
            rows = (
                await session.scalars(
                    select(WatermarkTaskRow)
                    .where(
                        WatermarkTaskRow.status.in_(["running", "failed", "cancelled"]),
                        (WatermarkTaskRow.lease_expires_at.is_(None))
                        | (
                            WatermarkTaskRow.lease_expires_at
                            < utc_now() - timedelta(seconds=120)
                        ),
                        WatermarkTaskRow.object_key.is_not(None),
                    )
                    .with_for_update(skip_locked=True)
                    .limit(20)
                )
            ).all()
            for row in rows:
                if row.object_key:
                    cleanup.append(row.object_key)
                if row.status == "running":
                    row.status = "failed"
                    row.error_code = "worker_interrupted"
                row.updated_at = utc_now()
        return cleanup

    async def cleaned(self, key: str) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(WatermarkTaskRow)
                .where(WatermarkTaskRow.object_key == key)
                .with_for_update()
            )
            if row is not None and row.status in {"failed", "cancelled"}:
                row.object_key = None
                row.size_bytes = 0
                row.lease_owner = None
                row.lease_expires_at = None

    async def release(self, task_id: UUID, worker: str, attempt: int) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.get(WatermarkTaskRow, task_id, with_for_update=True)
            if row is not None and row.lease_owner == worker and row.attempt == attempt:
                if row.status == "running":
                    row.status = "failed"
                    row.error_code = "worker_interrupted"
                row.lease_owner = None
                row.lease_expires_at = None
                row.updated_at = utc_now()

    async def offline(self, worker: str) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.get(WatermarkWorkerRow, worker)
            if row is not None:
                await session.delete(row)
