"""Transactional outbox polling with confirmed at-least-once publishing."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, cast
from uuid import UUID

from app.integrations.messaging.envelope import (
    EventEnvelope,
    EventEnvelopeError,
    JsonValue,
)
from app.repositories.contracts import OutboxSnapshot


class OutboxStateConflict(RuntimeError):
    """The claimed outbox lease was lost before its result was stored."""


class OutboxRepository(Protocol):
    async def claim_outbox(
        self,
        publisher_id: str,
        now: datetime,
        lease_for: timedelta,
        *,
        limit: int,
    ) -> tuple[OutboxSnapshot, ...]: ...

    async def mark_outbox_published(
        self, event_id: UUID, publisher_id: str, now: datetime
    ) -> bool: ...

    async def mark_outbox_failed(
        self,
        event_id: UUID,
        publisher_id: str,
        now: datetime,
        error: str,
        retry_at: datetime,
    ) -> bool: ...


class EventPublisher(Protocol):
    async def publish(self, envelope: EventEnvelope) -> None: ...


@dataclass(frozen=True, slots=True)
class OutboxLoopSettings:
    batch_size: int = 50
    claim_lease: timedelta = timedelta(seconds=60)
    poll_interval: float = 1.0
    retry_base: float = 1.0
    retry_max: float = 60.0

    def __post_init__(self) -> None:
        if not 1 <= self.batch_size <= 200:
            raise ValueError("outbox batch size must be between 1 and 200")
        if self.claim_lease <= timedelta(0):
            raise ValueError("outbox claim lease must be positive")
        if self.poll_interval <= 0:
            raise ValueError("outbox poll interval must be positive")
        if self.retry_base <= 0 or self.retry_max < self.retry_base:
            raise ValueError("outbox retry bounds are invalid")


class OutboxPublisherLoop:
    def __init__(
        self,
        *,
        repository: OutboxRepository,
        publisher: EventPublisher,
        publisher_id: str,
        clock: Callable[[], datetime],
        settings: OutboxLoopSettings | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        if not publisher_id.strip():
            raise ValueError("publisher id cannot be blank")
        self._repository = repository
        self._publisher = publisher
        self._publisher_id = publisher_id
        self._clock = clock
        self._settings = settings or OutboxLoopSettings()
        self._sleeper = sleeper
        self._random = random_value

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            processed = await self.run_once()
            if processed == 0 and not stop.is_set():
                await self._idle_until_stop(stop)

    async def run_once(self) -> int:
        now = self._now()
        events = await self._repository.claim_outbox(
            self._publisher_id,
            now,
            self._settings.claim_lease,
            limit=self._settings.batch_size,
        )
        for event in events:
            try:
                envelope = self._envelope(event)
                await self._publisher.publish(envelope)
            except asyncio.CancelledError:
                await asyncio.shield(self._mark_failed(event, "publisher_cancelled"))
                raise
            except EventEnvelopeError:
                await self._mark_failed(event, "event_validation_failed")
            except Exception as exc:
                code = f"broker_publish_failed:{type(exc).__name__}"
                await self._mark_failed(event, code)
            else:
                marked = await self._repository.mark_outbox_published(
                    event.id, self._publisher_id, self._now()
                )
                if not marked:
                    raise OutboxStateConflict("outbox publish lease was lost")
        return len(events)

    async def _mark_failed(self, event: OutboxSnapshot, code: str) -> None:
        now = self._now()
        retry_at = now + timedelta(seconds=self._retry_delay(event.publish_attempts))
        marked = await self._repository.mark_outbox_failed(
            event.id,
            self._publisher_id,
            now,
            code,
            retry_at,
        )
        if not marked:
            raise OutboxStateConflict("outbox failure lease was lost")

    def _retry_delay(self, attempts: int) -> float:
        exponent = min(max(attempts - 1, 0), 20)
        base = min(self._settings.retry_max, self._settings.retry_base * 2**exponent)
        random_value = self._random()
        if not 0 <= random_value <= 1:
            raise ValueError("random jitter must be between 0 and 1")
        return float(min(self._settings.retry_max, base * (0.5 + random_value)))

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("outbox clock must return an aware datetime")
        return now

    @staticmethod
    def _envelope(event: OutboxSnapshot) -> EventEnvelope:
        return EventEnvelope(
            schema_version=1,
            event_id=event.id,
            aggregate_id=event.aggregate_id,
            event_type=event.event_type,
            occurred_at=event.created_at,
            payload=cast(dict[str, JsonValue], event.payload),
        )

    async def _idle_until_stop(self, stop: asyncio.Event) -> None:
        sleeping = asyncio.ensure_future(self._sleeper(self._settings.poll_interval))
        stopping = asyncio.create_task(stop.wait())
        tasks = {sleeping, stopping}
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
