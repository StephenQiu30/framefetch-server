from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.integrations.messaging.envelope import EventEnvelope
from app.integrations.messaging.topology import RabbitMqTopology
from app.services.download_execution.models import ExecutionDisposition
from app.workers.download.consumer import _declare_download_topology, process_delivery


class FakeDelivery:
    def __init__(self, body: bytes, *, redelivered: bool = False) -> None:
        self.body = body
        self.redelivered = redelivered
        self.headers: dict[str, object] = {}
        self.acked = 0
        self.nacked: list[bool] = []

    async def ack(self) -> None:
        self.acked += 1

    async def nack(self, *, requeue: bool) -> None:
        self.nacked.append(requeue)


class FakeHandler:
    def __init__(self, result=ExecutionDisposition.ACK) -> None:
        self.result = result
        self.error: Exception | None = None

    async def execute(self, job_id):
        if self.error is not None:
            raise self.error
        return self.result


def body() -> bytes:
    job_id = uuid4()
    return EventEnvelope(
        schema_version=1,
        event_id=uuid4(),
        aggregate_id=job_id,
        event_type="download.requested",
        occurred_at=datetime.now(UTC),
        payload={"job_id": str(job_id), "attempt": 0, "version": 0},
    ).to_bytes()


@pytest.mark.asyncio
async def test_consumer_acks_only_converged_execution() -> None:
    success = FakeDelivery(body())
    await process_delivery(success, FakeHandler())
    assert (success.acked, success.nacked) == (1, [])

    retry = FakeDelivery(body())
    await process_delivery(retry, FakeHandler(ExecutionDisposition.REQUEUE))
    assert (retry.acked, retry.nacked) == (0, [True])


@pytest.mark.asyncio
async def test_consumer_dead_letters_bad_contract_and_requeues_faults() -> None:
    invalid = FakeDelivery(b"not-json")
    await process_delivery(invalid, FakeHandler())
    assert invalid.nacked == [False]

    transient = FakeDelivery(body())
    handler = FakeHandler()
    handler.error = OSError("database unavailable")
    await process_delivery(transient, handler)
    assert transient.nacked == [True]

    poison = FakeDelivery(body(), redelivered=True)
    await process_delivery(poison, handler)
    assert poison.nacked == [False]


@pytest.mark.asyncio
async def test_consumer_logs_the_delivery_retry_budget(
    caplog: pytest.LogCaptureFixture,
) -> None:
    poison = FakeDelivery(body(), redelivered=True)
    handler = FakeHandler()
    handler.error = OSError("database unavailable")

    with caplog.at_level(logging.WARNING):
        await process_delivery(poison, handler)

    record = caplog.records[-1]
    assert record.message == "download delivery dead_lettered"
    assert record.delivery_attempt == 2
    assert record.delivery_attempt_budget == 2
    assert record.delivery_budget_remaining == 0
    assert record.dlq_replay_count == 0


class FakeQueue:
    def __init__(self, bindings: list[tuple[object, str]]) -> None:
        self.bindings = bindings

    async def bind(self, exchange: object, *, routing_key: str) -> None:
        self.bindings.append((exchange, routing_key))


class FakeExchange:
    pass


class FakeChannel:
    def __init__(self) -> None:
        self.exchanges: list[tuple[str, object, bool]] = []
        self.queues: list[tuple[str, bool, dict[str, object]]] = []
        self.exchange = FakeExchange()
        self.dead_exchange = FakeExchange()
        self.bindings: list[tuple[object, str]] = []

    async def declare_exchange(self, name, *, type, durable):
        self.exchanges.append((name, type, durable))
        return self.dead_exchange if name.endswith(".dead") else self.exchange

    async def declare_queue(self, name, *, durable, arguments):
        self.queues.append((name, durable, arguments))
        return FakeQueue(self.bindings)


@pytest.mark.asyncio
async def test_download_topology_declares_and_binds_the_dead_letter_queue() -> None:
    channel = FakeChannel()
    topology = RabbitMqTopology("video.events", "video.download", "download.requested")

    await _declare_download_topology(channel, topology)

    assert [name for name, _, _ in channel.exchanges] == [
        "video.events",
        "video.events.dead",
    ]
    assert channel.queues[0][2] == {
        "x-message-ttl": 86_400_000,
        "x-max-length": 10_000,
        "x-dead-letter-exchange": "video.events.dead",
        "x-dead-letter-routing-key": "video.download.dead",
    }
    assert channel.queues[1] == (
        "video.download.dead",
        True,
        {"x-max-length": 10_000},
    )
    assert channel.bindings == [
        (channel.exchange, "download.requested"),
        (channel.dead_exchange, "video.download.dead"),
    ]
