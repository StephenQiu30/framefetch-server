from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from app.workers.outbox.loop import OutboxLoopSettings, OutboxPublisherLoop


class EmptyRepository:
    def __init__(self) -> None:
        self.claims = 0
        self.claimed = asyncio.Event()

    async def claim_outbox(self, *args, **kwargs):
        self.claims += 1
        self.claimed.set()
        return ()

    async def mark_outbox_published(self, *args, **kwargs):
        raise AssertionError("nothing was claimed")

    async def mark_outbox_failed(self, *args, **kwargs):
        raise AssertionError("nothing was claimed")


class NoopPublisher:
    async def publish(self, envelope) -> None:
        raise AssertionError("nothing was claimed")


@pytest.mark.asyncio
async def test_empty_poll_sleeps_once_and_stops_gracefully() -> None:
    repository = EmptyRepository()
    stop = asyncio.Event()
    sleeps = []

    async def sleeper(delay: float) -> None:
        sleeps.append(delay)
        stop.set()

    publisher_loop = OutboxPublisherLoop(
        repository=repository,
        publisher=NoopPublisher(),
        publisher_id="publisher-1",
        clock=lambda: datetime(2026, 8, 6, tzinfo=UTC),
        sleeper=sleeper,
        settings=OutboxLoopSettings(poll_interval=0.25),
    )
    await publisher_loop.run(stop)
    assert repository.claims == 1
    assert sleeps == [0.25]


@pytest.mark.asyncio
async def test_pre_stopped_loop_does_not_claim() -> None:
    repository = EmptyRepository()
    stop = asyncio.Event()
    stop.set()
    publisher_loop = OutboxPublisherLoop(
        repository=repository,
        publisher=NoopPublisher(),
        publisher_id="publisher-1",
        clock=lambda: datetime(2026, 8, 6, tzinfo=UTC),
    )
    await publisher_loop.run(stop)
    assert repository.claims == 0


@pytest.mark.asyncio
async def test_cancelling_idle_poll_cleans_up_sleeper() -> None:
    repository = EmptyRepository()
    stop = asyncio.Event()
    sleeper_cancelled = asyncio.Event()

    async def sleeper(delay: float) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            sleeper_cancelled.set()
            raise

    publisher_loop = OutboxPublisherLoop(
        repository=repository,
        publisher=NoopPublisher(),
        publisher_id="publisher-1",
        clock=lambda: datetime(2026, 8, 6, tzinfo=UTC),
        sleeper=sleeper,
    )
    task = asyncio.create_task(publisher_loop.run(stop))
    await repository.claimed.wait()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sleeper_cancelled.is_set()
