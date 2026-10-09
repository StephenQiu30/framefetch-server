"""aio-pika robust publisher with mandatory broker confirmations."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

import aio_pika
from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractExchange, AbstractRobustConnection
from pamqp.commands import Basic

from app.integrations.messaging.connection import configured_rabbitmq_url
from app.integrations.messaging.envelope import EventEnvelope
from app.integrations.messaging.topology import RabbitMqTopology, declare_durable_queue


class PublishNotConfirmed(RuntimeError):
    """RabbitMQ did not positively acknowledge a mandatory publish."""


class RabbitMqPublisher:
    def __init__(
        self,
        url: str,
        topology: RabbitMqTopology,
        *,
        connection_timeout: float = 10,
        publish_timeout: float = 10,
        heartbeat: int = 60,
        reconnect_interval: float = 5,
        connection_name: str = "framefetch-server-outbox",
        app_id: str = "framefetch-server-outbox",
    ) -> None:
        if not url:
            raise ValueError("RabbitMQ URL cannot be blank")
        if (
            connection_timeout <= 0
            or publish_timeout <= 0
            or heartbeat < 10
            or reconnect_interval <= 0
        ):
            raise ValueError("invalid RabbitMQ publisher settings")
        self._url = url
        self._topology = topology
        self._connection_timeout = connection_timeout
        self._publish_timeout = publish_timeout
        self._heartbeat = heartbeat
        self._reconnect_interval = reconnect_interval
        self._connection_name = connection_name
        self._app_id = app_id
        self._connection: AbstractRobustConnection | None = None
        self._exchange: AbstractExchange | None = None

    async def start(self) -> None:
        if self._connection is not None:
            return
        connection = await aio_pika.connect_robust(
            configured_rabbitmq_url(
                self._url,
                heartbeat=self._heartbeat,
                reconnect_interval=self._reconnect_interval,
                connection_name=self._connection_name,
            ),
            timeout=self._connection_timeout,
        )
        self._connection = connection
        try:
            async with asyncio.timeout(self._connection_timeout):
                channel = await connection.channel(
                    publisher_confirms=True,
                    on_return_raises=True,
                )
                for binding in self._topology.durable_queues:
                    await declare_durable_queue(channel, self._topology, binding)
                exchange = await channel.declare_exchange(
                    self._topology.exchange, passive=True
                )
            self._exchange = exchange
        except BaseException:
            await asyncio.shield(self.close())
            raise

    async def publish(
        self,
        envelope: EventEnvelope,
        *,
        headers: Mapping[str, str | int] | None = None,
    ) -> None:
        if self._exchange is None:
            raise RuntimeError("RabbitMQ publisher has not been started")
        message = Message(
            envelope.to_bytes(),
            content_type="application/json",
            content_encoding="utf-8",
            delivery_mode=DeliveryMode.PERSISTENT,
            correlation_id=str(envelope.aggregate_id),
            message_id=str(envelope.event_id),
            timestamp=envelope.occurred_at,
            type=envelope.event_type,
            app_id=self._app_id,
            headers={"schema_version": envelope.schema_version, **(headers or {})},
        )
        confirmation = await self._exchange.publish(
            message,
            routing_key=envelope.event_type,
            mandatory=True,
            timeout=self._publish_timeout,
        )
        if not isinstance(confirmation, Basic.Ack):
            raise PublishNotConfirmed("broker did not ack mandatory publish")

    async def close(self) -> None:
        connection = self._connection
        self._connection = None
        self._exchange = None
        if connection is not None:
            await connection.close()
