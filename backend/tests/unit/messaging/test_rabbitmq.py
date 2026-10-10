from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from aio_pika import DeliveryMode
from app.integrations.messaging.connection import configured_rabbitmq_url
from app.integrations.messaging.envelope import EventEnvelope
from app.integrations.messaging.rabbitmq import PublishNotConfirmed, RabbitMqPublisher
from app.integrations.messaging.topology import RabbitMqTopology
from pamqp.commands import Basic


class FakeExchange:
    def __init__(self, confirmation=None) -> None:
        self.confirmation = confirmation or Basic.Ack()
        self.published = []

    async def publish(self, message, routing_key, *, mandatory, timeout):
        self.published.append((message, routing_key, mandatory, timeout))
        return self.confirmation


class FakeQueue:
    def __init__(self) -> None:
        self.bindings = []

    async def bind(self, exchange, routing_key):
        self.bindings.append((exchange, routing_key))


class FakeChannel:
    def __init__(self) -> None:
        self.main = FakeExchange()
        self.dead = FakeExchange()
        self.queue = FakeQueue()
        self.dead_queue = FakeQueue()
        self.exchange_calls = []
        self.queue_calls = []

    async def declare_exchange(self, name, *, passive=False, type=None, durable=False):
        self.exchange_calls.append((name, passive))
        return self.dead if name.endswith(".dead") else self.main

    async def declare_queue(self, name, *, durable, arguments=None):
        self.queue_calls.append((name, durable, arguments))
        return self.dead_queue if name.endswith(".dead") else self.queue


class FakeConnection:
    def __init__(self) -> None:
        self.channel_value = FakeChannel()
        self.channel_calls = []
        self.closed = False

    async def channel(self, *, publisher_confirms, on_return_raises):
        self.channel_calls.append((publisher_confirms, on_return_raises))
        return self.channel_value

    async def close(self):
        self.closed = True


def event() -> EventEnvelope:
    return EventEnvelope(
        schema_version=1,
        event_id=uuid4(),
        aggregate_id=uuid4(),
        event_type="download.requested",
        occurred_at=datetime(2026, 8, 6, tzinfo=UTC),
        payload={"job_id": str(uuid4()), "attempt": 0, "version": 0},
    )


def test_topology_includes_bounded_import_queue_and_dlq() -> None:
    topology = RabbitMqTopology("video.events", "video.download", "download.requested")

    assert topology.imports.queue == "video.import"
    assert topology.imports.routing_key == "content.import.verify.requested"
    assert topology.imports.dead_queue == "video.import.dead"
    assert topology.imports in topology.durable_queues
    assert topology.download.dead_queue == "video.download.dead"


@pytest.mark.asyncio
async def test_robust_topology_and_confirmed_mandatory_publish(monkeypatch) -> None:
    connection = FakeConnection()

    async def connect(url, **kwargs):
        parsed = urlsplit(url)
        assert parsed.scheme == "amqp" and parsed.hostname == "broker"
        assert parse_qs(parsed.query) == {
            "heartbeat": ["60"],
            "reconnect_interval": ["5"],
            "name": ["framefetch-server-outbox"],
        }
        assert kwargs["timeout"] == 10
        return connection

    monkeypatch.setattr(
        "app.integrations.messaging.rabbitmq.aio_pika.connect_robust", connect
    )
    topology = RabbitMqTopology("video.events", "video.download", "download.requested")
    publisher = RabbitMqPublisher("amqp://broker/", topology)
    await publisher.start()
    await publisher.publish(event())

    channel = connection.channel_value
    assert connection.channel_calls == [(True, True)]
    assert channel.exchange_calls[-1] == ("video.events", True)
    assert [name for name, _, _ in channel.queue_calls] == [
        "video.download",
        "video.download.dead",
        "video.analysis-report",
        "video.analysis-report.dead",
        "video.import",
        "video.import.dead",
        "video.watermark",
        "video.watermark.dead",
    ]
    assert [routing_key for _, routing_key in channel.queue.bindings] == [
        "download.requested",
        "analysis.report.publish.requested",
        "content.import.verify.requested",
        "watermark.requested",
    ]
    assert [routing_key for _, routing_key in channel.dead_queue.bindings] == [
        "video.download.dead",
        "video.analysis-report.dead",
        "video.import.dead",
        "video.watermark.dead",
    ]
    message, routing_key, mandatory, timeout = channel.main.published[0]
    assert (routing_key, mandatory, timeout) == ("download.requested", True, 10)
    assert message.delivery_mode is DeliveryMode.PERSISTENT
    assert message.message_id is not None
    await publisher.close()
    assert connection.closed


def test_connection_url_preserves_vhost_and_overrides_runtime_options() -> None:
    result = configured_rabbitmq_url(
        "amqps://worker:secret@rabbit.internal:5671/video?heartbeat=30&locale=en_US",
        heartbeat=90,
        reconnect_interval=2.5,
        connection_name="analysis worker 1",
    )
    parsed = urlsplit(result)
    assert (parsed.scheme, parsed.hostname, parsed.port, parsed.path) == (
        "amqps",
        "rabbit.internal",
        5671,
        "/video",
    )
    assert parse_qs(parsed.query) == {
        "heartbeat": ["90"],
        "locale": ["en_US"],
        "reconnect_interval": ["2.5"],
        "name": ["analysis worker 1"],
    }


@pytest.mark.asyncio
async def test_nack_is_not_treated_as_success(monkeypatch) -> None:
    connection = FakeConnection()
    connection.channel_value.main.confirmation = Basic.Nack()

    async def connect(*args, **kwargs):
        return connection

    monkeypatch.setattr(
        "app.integrations.messaging.rabbitmq.aio_pika.connect_robust", connect
    )
    publisher = RabbitMqPublisher(
        "amqp://broker/",
        RabbitMqTopology("video.events", "video.download", "download.requested"),
    )
    await publisher.start()
    with pytest.raises(PublishNotConfirmed):
        await publisher.publish(event())


@pytest.mark.asyncio
async def test_topology_failure_closes_partial_connection(monkeypatch) -> None:
    connection = FakeConnection()

    async def fail_exchange(*args, **kwargs):
        raise RuntimeError("topology declaration failed")

    connection.channel_value.declare_exchange = fail_exchange

    async def connect(*args, **kwargs):
        return connection

    monkeypatch.setattr(
        "app.integrations.messaging.rabbitmq.aio_pika.connect_robust", connect
    )
    publisher = RabbitMqPublisher(
        "amqp://broker/",
        RabbitMqTopology("video.events", "video.download", "download.requested"),
    )
    with pytest.raises(RuntimeError):
        await publisher.start()
    assert connection.closed
