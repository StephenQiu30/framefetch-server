from __future__ import annotations

import asyncio

import pytest
from app.workers.runner.active_tasks import ActiveTaskRegistry
from app.workers.runner.contracts import RunnerTaskStage


async def test_stage_and_progress_are_monotonic() -> None:
    registry = ActiveTaskRegistry(2)
    task = asyncio.current_task()
    assert task is not None
    registry.register("job", task)
    registry.update("job", RunnerTaskStage.DOWNLOADING, 10)
    registry.update("job", RunnerTaskStage.DOWNLOADING, 40)

    with pytest.raises(ValueError):
        registry.update("job", RunnerTaskStage.REVALIDATING, 50)
    with pytest.raises(ValueError):
        registry.update("job", RunnerTaskStage.DOWNLOADING, 39)

    snapshot = registry.status("job")
    assert snapshot is not None
    assert snapshot.stage is RunnerTaskStage.DOWNLOADING
    assert snapshot.progress == 40


async def test_ready_record_is_bounded_and_evictable() -> None:
    registry = ActiveTaskRegistry(1)
    task = asyncio.current_task()
    assert task is not None
    registry.register("first", task)
    registry.complete("first", task)
    ready = registry.status("first")
    assert ready is not None
    assert ready.stage is RunnerTaskStage.READY
    assert ready.progress == 100

    registry.register("second", task)

    assert registry.status("first") is None
    assert registry.status("second") is not None


async def test_cancel_acknowledges_only_after_cleanup_and_is_idempotent():
    registry = ActiveTaskRegistry(2)
    started, cleaning, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def work():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await finish.wait()

    task = asyncio.create_task(work())
    registry.register("job", task)
    await started.wait()
    cancel = asyncio.create_task(registry.cancel("job"))
    await cleaning.wait()
    assert not cancel.done()
    finish.set()
    await asyncio.wait_for(cancel, 1)
    assert task.done()
    await registry.cancel("job")
    await registry.cancel("unknown")
