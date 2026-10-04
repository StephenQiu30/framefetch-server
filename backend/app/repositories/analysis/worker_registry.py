"""Database-backed analysis worker liveness and protocol compatibility."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import as_utc
from app.models import AnalysisWorkerHeartbeatRow

# 3: CreationWorkflow replaces retired SkillWorkflow commands on Temporal.
ANALYSIS_MESSAGE_SCHEMA_VERSION = 3


class SqlAlchemyAnalysisWorkerRegistry:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        expected_app_version: str,
        expected_message_schema_version: int,
        stale_after: timedelta,
    ) -> None:
        if not expected_app_version or expected_message_schema_version <= 0:
            raise ValueError("invalid analysis worker capability")
        if stale_after <= timedelta(0):
            raise ValueError("analysis worker heartbeat lifetime must be positive")
        self._sessions = sessions
        self._expected_app_version = expected_app_version
        self._expected_message_schema_version = expected_message_schema_version
        self._stale_after = stale_after

    async def heartbeat(
        self,
        worker_id: str,
        *,
        app_version: str,
        message_schema_version: int,
        now: datetime,
    ) -> None:
        if not worker_id or not app_version or message_schema_version <= 0:
            raise ValueError("invalid analysis worker heartbeat")
        async with self._sessions() as session, session.begin():
            row = await session.get(AnalysisWorkerHeartbeatRow, worker_id)
            if row is None:
                session.add(
                    AnalysisWorkerHeartbeatRow(
                        worker_id=worker_id,
                        app_version=app_version,
                        message_schema_version=message_schema_version,
                        last_seen_at=now,
                    )
                )
                return
            row.app_version = app_version
            row.message_schema_version = message_schema_version
            row.last_seen_at = now

    async def unregister(self, worker_id: str) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                delete(AnalysisWorkerHeartbeatRow).where(
                    AnalysisWorkerHeartbeatRow.worker_id == worker_id
                )
            )

    async def is_available(self, now: datetime) -> bool:
        cutoff = as_utc(now) - self._stale_after
        async with self._sessions() as session:
            worker = await session.scalar(
                select(AnalysisWorkerHeartbeatRow.worker_id)
                .where(
                    AnalysisWorkerHeartbeatRow.app_version
                    == self._expected_app_version,
                    AnalysisWorkerHeartbeatRow.message_schema_version
                    == self._expected_message_schema_version,
                    AnalysisWorkerHeartbeatRow.last_seen_at >= cutoff,
                )
                .limit(1)
            )
            return worker is not None
