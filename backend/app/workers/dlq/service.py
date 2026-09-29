from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.integrations.messaging import EventEnvelope, EventEnvelopeError
from app.workers.dlq.repository import ReplayAudit

ALLOWED_EVENTS = {
    "video.download.dead": "download.requested",
    "video.import.dead": "content.import.verify.requested",
    "video.analysis-report.dead": "analysis.report.publish.requested",
}


class ReplayDelivery(Protocol):
    @property
    def body(self) -> bytes: ...

    @property
    def headers(self) -> Mapping[str, object] | None: ...

    async def ack(self) -> None: ...

    async def nack(self, *, requeue: bool) -> None: ...


class ReplayRepository(Protocol):
    async def get_or_create(
        self,
        *,
        source_queue: str,
        original_event_id: UUID,
        replay_count: int,
        actor: str,
        reason: str,
        now: datetime,
    ) -> ReplayAudit: ...

    async def mark_published(self, audit_id: UUID, now: datetime) -> None: ...

    async def mark_failed(self, audit_id: UUID, code: str, now: datetime) -> None: ...


class ReplayPublisher(Protocol):
    async def publish(
        self, envelope: EventEnvelope, *, headers: Mapping[str, str | int] | None = None
    ) -> None: ...


class DlqReplayService:
    def __init__(
        self,
        repository: ReplayRepository,
        publisher: ReplayPublisher,
        clock: Callable[[], datetime],
        *,
        max_replays: int = 3,
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._clock = clock
        self._max_replays = max_replays

    async def replay(
        self,
        delivery: ReplayDelivery,
        *,
        source_queue: str,
        actor: str,
        reason: str,
    ) -> ReplayAudit:
        try:
            original = EventEnvelope.from_bytes(delivery.body)
            if ALLOWED_EVENTS.get(source_queue) != original.event_type:
                raise EventEnvelopeError("event does not belong to the selected DLQ")
            previous = _replay_count(delivery.headers)
            if previous >= self._max_replays:
                raise EventEnvelopeError("DLQ replay limit reached")
        except (EventEnvelopeError, TypeError, ValueError):
            await delivery.nack(requeue=True)
            raise
        replay_count = previous + 1
        now = self._clock()
        audit = await self._repository.get_or_create(
            source_queue=source_queue,
            original_event_id=original.event_id,
            replay_count=replay_count,
            actor=actor,
            reason=reason,
            now=now,
        )
        if audit.status == "published":
            await delivery.ack()
            return audit
        replay = EventEnvelope(
            schema_version=original.schema_version,
            event_id=audit.replay_event_id,
            aggregate_id=original.aggregate_id,
            event_type=original.event_type,
            occurred_at=audit.created_at,
            payload=original.payload,
        )
        try:
            await self._publisher.publish(
                replay,
                headers={
                    "x-replay-count": replay_count,
                    "x-original-event-id": str(original.event_id),
                },
            )
        except Exception as exc:
            await self._repository.mark_failed(
                audit.id, f"publish_failed:{type(exc).__name__}", self._clock()
            )
            await delivery.nack(requeue=True)
            raise
        await self._repository.mark_published(audit.id, self._clock())
        await delivery.ack()
        return audit


def _replay_count(headers: Mapping[str, object] | None) -> int:
    value = (headers or {}).get("x-replay-count", 0)
    if type(value) is not int or not 0 <= value <= 3:
        raise ValueError("invalid replay count")
    return value
