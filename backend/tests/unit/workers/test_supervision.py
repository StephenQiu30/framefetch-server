from __future__ import annotations

import asyncio

import pytest
from app.workers.supervision import run_resilient


@pytest.mark.asyncio
async def test_failing_component_restarts_without_stopping_siblings() -> None:
    stop = asyncio.Event()
    attempts = 0
    healthy_running = asyncio.Event()
    recovered = asyncio.Event()

    async def flaky(event: asyncio.Event) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("broker unavailable")
        recovered.set()
        await event.wait()

    async def healthy(event: asyncio.Event) -> None:
        healthy_running.set()
        await event.wait()

    tasks = [
        asyncio.create_task(run_resilient("flaky", flaky, stop, initial_delay=0.01)),
        asyncio.create_task(run_resilient("healthy", healthy, stop)),
    ]
    await asyncio.wait_for(recovered.wait(), 2)
    assert healthy_running.is_set() and not tasks[1].done()
    assert attempts == 3
    stop.set()
    await asyncio.wait_for(asyncio.gather(*tasks), 2)
