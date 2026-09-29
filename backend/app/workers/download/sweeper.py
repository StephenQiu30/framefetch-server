from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.workers.download.workspace import SharedWorkspaceCleaner

_log = logging.getLogger(__name__)


class RecoveryRepository(Protocol):
    async def active_workspace_task_ids(self, now: datetime) -> frozenset[str]: ...

    async def recover_stale_queued(
        self,
        now: datetime,
        stale_before: datetime,
        *,
        limit: int = 100,
    ) -> tuple[UUID, ...]: ...

    async def reclaim_stale(
        self, now: datetime, *, limit: int = 100
    ) -> tuple[UUID, ...]: ...

    async def release_ready_retries(
        self, now: datetime, *, limit: int = 100
    ) -> tuple[UUID, ...]: ...


@dataclass(frozen=True, slots=True)
class RecoverySettings:
    interval: float = 5.0
    batch_size: int = 100
    queued_stale_after: timedelta = timedelta(seconds=60)
    workspace_gc_after: timedelta = timedelta(hours=24)

    def __post_init__(self) -> None:
        if (
            self.interval <= 0
            or not 1 <= self.batch_size <= 1000
            or self.queued_stale_after <= timedelta(0)
            or self.workspace_gc_after <= timedelta(0)
        ):
            raise ValueError("invalid recovery settings")


class DownloadRecoverySweeper:
    def __init__(
        self,
        repository: RecoveryRepository,
        clock: Callable[[], datetime],
        settings: RecoverySettings | None = None,
        workspace_cleaner: SharedWorkspaceCleaner | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._settings = settings or RecoverySettings()
        self._workspace_cleaner = workspace_cleaner

    async def tick(
        self,
    ) -> tuple[tuple[UUID, ...], tuple[UUID, ...], tuple[UUID, ...]]:
        now = self._clock()
        queued = await self._repository.recover_stale_queued(
            now,
            now - self._settings.queued_stale_after,
            limit=self._settings.batch_size,
        )
        stale = await self._repository.reclaim_stale(
            now, limit=self._settings.batch_size
        )
        ready = await self._repository.release_ready_retries(
            now, limit=self._settings.batch_size
        )
        await self._collect_orphans(now)
        return queued, stale, ready

    async def _collect_orphans(self, now: datetime) -> None:
        cleaner = self._workspace_cleaner
        if cleaner is None:
            return
        active = await self._repository.active_workspace_task_ids(now)
        removed = await cleaner.collect_orphans(
            active,
            now=now,
            older_than=self._settings.workspace_gc_after,
        )
        if removed:
            _log.info(
                "download workspace orphans removed", extra={"count": len(removed)}
            )

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.tick()
            except Exception:
                _log.exception("download recovery sweep failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._settings.interval)
            except TimeoutError:
                continue
