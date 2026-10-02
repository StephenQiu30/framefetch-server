from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.integrations.messaging.envelope import EventEnvelope
from app.services.imports.events import (
    CONTENT_IMPORT_VERIFY_REQUESTED,
    import_verify_requested_payload,
)
from app.services.imports.models import ImportDisposition
from app.services.imports.rules.enums import ContentKind
from app.workers.imports.consumer import process_delivery

RESOURCE_ID = UUID("11111111-1111-4111-8111-111111111111")


def body() -> bytes:
    return EventEnvelope(
        schema_version=1,
        event_id=uuid4(),
        aggregate_id=RESOURCE_ID,
        event_type=CONTENT_IMPORT_VERIFY_REQUESTED,
        occurred_at=datetime(2026, 8, 14, tzinfo=UTC),
        payload=import_verify_requested_payload(RESOURCE_ID, ContentKind.VIDEO, 1, 2),
    ).to_bytes()


class FakeDelivery:
    def __init__(self, content: bytes, *, redelivered: bool = False) -> None:
        self.body = content
        self.redelivered = redelivered
        self.acked = False
        self.nacks: list[bool] = []

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, *, requeue: bool) -> None:
        self.nacks.append(requeue)


class FakeHandler:
    def __init__(
        self,
        disposition: ImportDisposition = ImportDisposition.ACK,
        error: BaseException | None = None,
    ) -> None:
        self.disposition = disposition
        self.error = error
        self.calls: list[tuple[UUID, ContentKind, int, int]] = []

    async def execute(
        self,
        resource_id: UUID,
        content_kind: ContentKind,
        attempt: int,
        expected_version: int,
    ) -> ImportDisposition:
        self.calls.append((resource_id, content_kind, attempt, expected_version))
        if self.error is not None:
            raise self.error
        return self.disposition


async def test_import_delivery_acks_only_after_handler_success() -> None:
    delivery = FakeDelivery(body())
    handler = FakeHandler()

    await process_delivery(delivery, handler)

    assert handler.calls == [(RESOURCE_ID, ContentKind.VIDEO, 1, 2)]
    assert delivery.acked is True
    assert delivery.nacks == []


async def test_import_delivery_dead_letters_malformed_message() -> None:
    delivery = FakeDelivery(b"{}")

    await process_delivery(delivery, FakeHandler())

    assert delivery.acked is False
    assert delivery.nacks == [False]


@pytest.mark.parametrize(
    ("redelivered", "expected_requeue"),
    ((False, True), (True, False)),
)
async def test_import_delivery_bounds_handler_retries(
    redelivered: bool, expected_requeue: bool
) -> None:
    delivery = FakeDelivery(body(), redelivered=redelivered)

    await process_delivery(delivery, FakeHandler(error=RuntimeError("failed")))

    assert delivery.acked is False
    assert delivery.nacks == [expected_requeue]


async def test_import_retry_disposition_uses_same_bounded_nack_policy() -> None:
    delivery = FakeDelivery(body(), redelivered=True)

    await process_delivery(delivery, FakeHandler(disposition=ImportDisposition.RETRY))

    assert delivery.acked is False
    assert delivery.nacks == [False]


async def test_import_delivery_requeues_on_consumer_cancellation() -> None:
    delivery = FakeDelivery(body())

    with pytest.raises(asyncio.CancelledError):
        await process_delivery(
            delivery,
            FakeHandler(error=asyncio.CancelledError()),
        )

    assert delivery.acked is False
    assert delivery.nacks == [True]
