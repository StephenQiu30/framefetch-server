from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.repositories.contracts import OutboxSnapshot
from app.workers.outbox.loop import OutboxLoopSettings, OutboxPublisherLoop

NOW = datetime(2026, 8, 6, 10, tzinfo=UTC)


def record(*, attempts: int = 1) -> OutboxSnapshot:
    return OutboxSnapshot(
        id=uuid4(),
        aggregate_type="download_job",
        aggregate_id=uuid4(),
        event_type="download.requested",
        payload={"job_id": str(uuid4()), "attempt": 0, "version": 0},
        publish_attempts=attempts,
        available_at=NOW,
        created_at=NOW,
    )


class FakeRepository:
    def __init__(self, batches) -> None:
        self.batches = list(batches)
        self.claims = []
        self.published = []
        self.failed = []
        self.publish_error = None

    async def claim_outbox(self, owner, now, lease_for, *, limit):
        self.claims.append((owner, now, lease_for, limit))
        return self.batches.pop(0) if self.batches else ()

    async def mark_outbox_published(self, event_id, owner, now):
        if self.publish_error is not None:
            raise self.publish_error
        self.published.append((event_id, owner, now))
        return True

    async def mark_outbox_failed(self, event_id, owner, now, error, retry_at):
        self.failed.append((event_id, owner, now, error, retry_at))
        return True


class FakePublisher:
    def __init__(self, error=None) -> None:
        self.error = error
        self.events = []

    async def publish(self, envelope) -> None:
        self.events.append(envelope)
        if self.error is not None:
            raise self.error


def loop(repository, publisher, **settings) -> OutboxPublisherLoop:
    return OutboxPublisherLoop(
        repository=repository,
        publisher=publisher,
        publisher_id="publisher-1",
        clock=lambda: NOW,
        random_value=lambda: 0.5,
        settings=OutboxLoopSettings(**settings),
    )


@pytest.mark.asyncio
async def test_confirm_is_required_before_marking_published() -> None:
    item = record()
    repository = FakeRepository([(item,)])
    publisher = FakePublisher()

    assert await loop(repository, publisher).run_once() == 1
    assert [event.event_id for event in publisher.events] == [item.id]
    assert repository.published[0][0] == item.id
    assert repository.failed == []


@pytest.mark.asyncio
async def test_publish_failure_releases_event_with_exponential_jitter() -> None:
    item = record(attempts=3)
    repository = FakeRepository([(item,)])
    publisher = FakePublisher(ConnectionError("secret broker details"))

    assert await loop(repository, publisher).run_once() == 1
    assert repository.published == []
    failure = repository.failed[0]
    assert failure[0] == item.id
    assert failure[3] == "broker_publish_failed:ConnectionError"
    assert failure[4] == NOW + timedelta(seconds=4)


@pytest.mark.asyncio
async def test_confirmed_duplicate_uses_same_event_id_after_db_failure() -> None:
    item = record()
    repository = FakeRepository([(item,), (item,)])
    repository.publish_error = RuntimeError("database unavailable")
    publisher = FakePublisher()
    publisher_loop = loop(repository, publisher)

    with pytest.raises(RuntimeError):
        await publisher_loop.run_once()
    repository.publish_error = None
    await publisher_loop.run_once()
    assert [event.event_id for event in publisher.events] == [item.id, item.id]
    assert repository.published[0][0] == item.id


@pytest.mark.asyncio
async def test_cancellation_marks_claimed_event_retryable() -> None:
    item = record()
    repository = FakeRepository([(item,)])
    publisher = FakePublisher(asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await loop(repository, publisher).run_once()
    assert repository.published == []
    assert repository.failed[0][3] == "publisher_cancelled"
