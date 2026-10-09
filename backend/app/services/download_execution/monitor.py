from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, TypeVar
from uuid import UUID

from app.services.download_execution.errors import LeaseInfrastructureError, LeaseLost
from app.services.download_execution.ports import (
    Clock,
    ExecutionRepository,
    ExecutionRunner,
    RunnerArtifactView,
    RunnerProgressView,
)
from app.services.downloads.rules.enums import DownloadStage, MediaKind
from app.services.downloads.rules.formats import DownloadPlan
from app.services.provider_types import ExecutionContext

ResultT = TypeVar("ResultT")
_STAGE_RANKS = {
    DownloadStage.REVALIDATING: 1,
    DownloadStage.DOWNLOADING: 2,
    DownloadStage.REMUXING: 3,
    DownloadStage.VERIFYING: 4,
    DownloadStage.UPLOADING: 5,
}
_MAX_RUNNER_STATUS_WAIT_SECONDS = 5.0


class LeaseMonitor:
    def __init__(
        self,
        *,
        repository: ExecutionRepository,
        runner: ExecutionRunner,
        job_id: UUID,
        worker_id: str,
        attempt: int,
        task_id: str,
        clock: Clock,
        lease_for: timedelta,
        interval: float,
    ) -> None:
        self._repository = repository
        self._runner = runner
        self._job_id = job_id
        self._worker_id = worker_id
        self._attempt = attempt
        self._task_id = task_id
        self._clock = clock
        self._lease_for = lease_for
        self._interval = interval

    async def run_download(
        self,
        url: str,
        plan: DownloadPlan | None,
        *,
        provider_media_id: str,
        extractor_key: str,
        duration_seconds: int,
        execution_context: ExecutionContext,
        media_kind: MediaKind = MediaKind.VIDEO,
        asset_count: int = 0,
    ) -> RunnerArtifactView:
        task = asyncio.create_task(
            self._runner.download(
                self._task_id,
                url,
                plan,
                expected_provider_media_id=provider_media_id,
                expected_extractor_key=extractor_key,
                expected_duration_seconds=duration_seconds,
                execution_context=execution_context,
                media_kind=media_kind,
                asset_count=asset_count,
            )
        )
        progress = _ProgressState()
        heartbeat = asyncio.create_task(self._heartbeat_loop(progress))
        status = asyncio.create_task(self._status_loop(progress))
        try:
            done, _ = await asyncio.wait(
                {task, heartbeat}, return_when=asyncio.FIRST_COMPLETED
            )
            if task in done:
                return await task
            await heartbeat
            raise LeaseInfrastructureError
        except (LeaseLost, LeaseInfrastructureError, asyncio.CancelledError):
            await self._abort(task, drain=False)
            raise
        finally:
            await _stop_tasks(heartbeat, status)

    async def run_fixed(
        self,
        operation: Callable[[], Coroutine[Any, Any, ResultT]],
        *,
        stage: DownloadStage,
        progress: int,
        drain_on_abort: bool,
    ) -> ResultT:
        try:
            await self._heartbeat(stage, progress)
        except (LeaseLost, LeaseInfrastructureError, asyncio.CancelledError):
            await self._cancel_runner()
            raise
        task: asyncio.Task[ResultT] = asyncio.create_task(operation())
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(
                _ProgressState(stage=stage, progress=progress), delay_first=True
            )
        )
        try:
            done, _ = await asyncio.wait(
                {task, heartbeat_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if task in done:
                return await task
            await heartbeat_task
            raise LeaseInfrastructureError
        except (LeaseLost, LeaseInfrastructureError, asyncio.CancelledError):
            await self._abort(task, drain=drain_on_abort)
            raise
        finally:
            await _stop_tasks(heartbeat_task)

    async def _heartbeat_loop(
        self, progress: _ProgressState, *, delay_first: bool = False
    ) -> None:
        if delay_first:
            await asyncio.sleep(self._interval)
        while True:
            await self._heartbeat(progress.stage, progress.progress)
            await asyncio.sleep(self._interval)

    async def _status_loop(self, progress: _ProgressState) -> None:
        while True:
            current = await self._runner_progress()
            progress.stage = current.stage
            progress.progress = current.progress
            await asyncio.sleep(self._interval)

    async def _runner_progress(self) -> RunnerProgressView:
        try:
            status_timeout = min(
                self._interval / 2,
                self._lease_for.total_seconds() / 4,
                _MAX_RUNNER_STATUS_WAIT_SECONDS,
            )
            async with asyncio.timeout(max(status_timeout, 0.001)):
                return await self._runner.status(self._task_id)
        except Exception:
            return _FallbackProgress()

    async def _heartbeat(self, stage: DownloadStage, progress: int) -> None:
        try:
            owned = await self._repository.heartbeat(
                self._job_id,
                self._worker_id,
                self._attempt,
                stage=stage.value,
                stage_rank=_STAGE_RANKS[stage],
                progress=progress,
                now=self._clock(),
                lease_for=self._lease_for,
            )
        except Exception as exc:
            raise LeaseInfrastructureError from exc
        if not owned:
            raise LeaseLost

    async def _abort(self, task: asyncio.Task[ResultT], *, drain: bool) -> None:
        await self._cancel_runner()
        if drain:
            with suppress(BaseException):
                await asyncio.shield(task)
            return
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _cancel_runner(self) -> None:
        with suppress(Exception):
            await self._runner.cancel(self._task_id)


@dataclass(slots=True)
class _ProgressState:
    stage: DownloadStage = DownloadStage.REVALIDATING
    progress: int = 0


class _FallbackProgress:
    stage = DownloadStage.REVALIDATING
    progress = 0


async def _stop_tasks(*tasks: asyncio.Task[object]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
