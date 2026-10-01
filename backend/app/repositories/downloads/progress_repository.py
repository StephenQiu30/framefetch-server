"""Lease-bound heartbeat and monotonic progress updates."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import case, update

from app.models import DownloadJobRow
from app.repositories.errors import LeaseConflict
from app.repositories.repository_base import RepositoryBase
from app.services.provider_types import ExecutionContext

STAGE_RANKS = {
    "revalidating": 1,
    "downloading": 2,
    "remuxing": 3,
    "verifying": 4,
    "uploading": 5,
}


class ProgressRepository(RepositoryBase):
    async def record_execution_context(
        self,
        job_id: UUID,
        worker_id: str,
        attempt: int,
        context: ExecutionContext,
        now: datetime,
    ) -> None:
        statement = (
            update(DownloadJobRow)
            .where(
                DownloadJobRow.id == job_id,
                DownloadJobRow.status == "running",
                DownloadJobRow.lease_owner == worker_id,
                DownloadJobRow.attempt == attempt,
                DownloadJobRow.lease_expires_at > now,
            )
            .values(
                execution_context=context.to_document(),
                execution_context_attempt=attempt,
                version=DownloadJobRow.version + 1,
                updated_at=now,
            )
            .returning(DownloadJobRow.id)
        )
        async with self._sessions() as session, session.begin():
            if await session.scalar(statement) is None:
                raise LeaseConflict("worker no longer owns this job attempt")

    async def heartbeat(
        self,
        job_id: UUID,
        worker_id: str,
        attempt: int,
        *,
        stage: str,
        stage_rank: int,
        progress: int,
        now: datetime,
        lease_for: timedelta,
    ) -> bool:
        if not 0 <= progress <= 100:
            raise ValueError("progress must be between 0 and 100")
        if STAGE_RANKS.get(stage) != stage_rank:
            raise ValueError("stage and stage_rank do not match")
        stage_advances = DownloadJobRow.stage_rank <= stage_rank
        statement = (
            update(DownloadJobRow)
            .where(
                DownloadJobRow.id == job_id,
                DownloadJobRow.status == "running",
                DownloadJobRow.lease_owner == worker_id,
                DownloadJobRow.attempt == attempt,
                DownloadJobRow.lease_expires_at > now,
            )
            .values(
                stage=case((stage_advances, stage), else_=DownloadJobRow.stage),
                stage_rank=case(
                    (stage_advances, stage_rank), else_=DownloadJobRow.stage_rank
                ),
                progress=case(
                    (DownloadJobRow.progress <= progress, progress),
                    else_=DownloadJobRow.progress,
                ),
                heartbeat_at=now,
                lease_expires_at=now + lease_for,
                version=DownloadJobRow.version + 1,
                updated_at=now,
            )
            .returning(DownloadJobRow.id)
        )
        async with self._sessions() as session, session.begin():
            return (await session.scalar(statement)) is not None
