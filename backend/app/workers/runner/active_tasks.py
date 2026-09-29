from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.workers.runner.contracts import RunnerTaskStage
from app.workers.runner.errors import RunnerFailure

_STAGE_ORDER = {stage: index for index, stage in enumerate(RunnerTaskStage)}


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    stage: RunnerTaskStage
    progress: int


@dataclass(slots=True)
class _TaskRecord:
    task: asyncio.Task[object] | None
    stage: RunnerTaskStage
    progress: int


class ActiveTaskRegistry:
    def __init__(self, max_tasks: int) -> None:
        if max_tasks <= 0:
            raise ValueError("active task limit must be positive")
        self._max_tasks = max_tasks
        self._tasks: dict[str, _TaskRecord] = {}

    def register(self, task_id: str, task: asyncio.Task[object]) -> None:
        if task_id in self._tasks:
            raise RunnerFailure("task_already_active", status=409)
        self._evict_ready()
        if len(self._tasks) >= self._max_tasks:
            raise RunnerFailure("runner_busy", status=503)
        self._tasks[task_id] = _TaskRecord(
            task,
            RunnerTaskStage.REVALIDATING,
            0,
        )

    def update(
        self,
        task_id: str,
        stage: RunnerTaskStage,
        progress: int,
    ) -> None:
        record = self._tasks.get(task_id)
        if record is None or record.task is None:
            raise RunnerFailure("task_not_found", status=404)
        if not 0 <= progress <= 100:
            raise ValueError("task progress is outside 0-100")
        stage_regressed = _STAGE_ORDER[stage] < _STAGE_ORDER[record.stage]
        if stage_regressed or progress < record.progress:
            raise ValueError("task stage and progress must be monotonic")
        record.stage = stage
        record.progress = progress

    def complete(self, task_id: str, task: asyncio.Task[object]) -> None:
        record = self._tasks.get(task_id)
        if record is None or record.task is not task:
            raise RunnerFailure("task_not_found", status=404)
        record.stage = RunnerTaskStage.READY
        record.progress = 100
        record.task = None

    def discard(self, task_id: str, task: asyncio.Task[object]) -> None:
        record = self._tasks.get(task_id)
        if record is not None and record.task is task:
            self._tasks.pop(task_id, None)

    async def cancel(self, task_id: str) -> None:
        record = self._tasks.get(task_id)
        task = record.task if record is not None else None
        if task is not None and not task.done() and task.cancelling() == 0:
            task.cancel()
        if task is not None:
            # Shield cleanup from the cancellation request disconnecting. A
            # timeout is uncertainty, never an acknowledgement of termination.
            try:
                async with asyncio.timeout(20):
                    await asyncio.shield(asyncio.gather(task, return_exceptions=True))
            except TimeoutError as exc:
                raise RunnerFailure("cancellation_pending", status=503) from exc

    def status(self, task_id: str) -> TaskSnapshot | None:
        record = self._tasks.get(task_id)
        if record is None:
            return None
        return TaskSnapshot(record.stage, record.progress)

    def _evict_ready(self) -> None:
        if len(self._tasks) < self._max_tasks:
            return
        for task_id, record in self._tasks.items():
            if record.task is None:
                self._tasks.pop(task_id)
                return
