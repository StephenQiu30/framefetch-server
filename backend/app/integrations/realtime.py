"""Bounded WebSocket fan-out fed by an exclusive RabbitMQ queue."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import aio_pika
from aio_pika.abc import (
    AbstractIncomingMessage,
    AbstractQueue,
    AbstractRobustConnection,
)

from app.integrations.messaging.connection import configured_rabbitmq_url
from app.integrations.messaging.envelope import EventEnvelope, EventEnvelopeError


@dataclass(slots=True, eq=False)
class RealtimeConnection:
    owner_hash: str
    id: UUID = field(default_factory=uuid4)
    queue: asyncio.Queue[dict[str, object]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=64)
    )
    subscriptions: set[tuple[str, UUID]] = field(default_factory=set)
    recovering: dict[tuple[str, UUID], list[dict[str, object]]] = field(
        default_factory=dict
    )
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class RealtimeConnectionLimit(RuntimeError):
    """The gateway or owner connection budget is exhausted."""


class RealtimeHub:
    def __init__(self, *, max_connections: int = 1000, max_per_owner: int = 4) -> None:
        self._max_connections = max_connections
        self._max_per_owner = max_per_owner
        self._connections: set[RealtimeConnection] = set()

    def register(self, owner_hash: str) -> RealtimeConnection:
        owner_connections = sum(
            connection.owner_hash == owner_hash for connection in self._connections
        )
        if (
            len(self._connections) >= self._max_connections
            or owner_connections >= self._max_per_owner
        ):
            raise RealtimeConnectionLimit("realtime connection limit reached")
        connection = RealtimeConnection(owner_hash)
        self._connections.add(connection)
        return connection

    def unregister(self, connection: RealtimeConnection) -> None:
        self._connections.discard(connection)

    def invalidate_owner(self, owner_hash: str) -> None:
        for connection in tuple(self._connections):
            if connection.owner_hash == owner_hash:
                self._enqueue(connection, {"type": "session.invalidated"})

    def begin_subscription(
        self, connection: RealtimeConnection, task_type: str, task_id: UUID
    ) -> None:
        key = (task_type, task_id)
        connection.subscriptions.add(key)
        connection.recovering[key] = []

    def finish_subscription(
        self, connection: RealtimeConnection, task_type: str, task_id: UUID
    ) -> None:
        key = (task_type, task_id)
        buffered = connection.recovering.pop(key, [])
        for event in sorted(buffered, key=self._event_version):
            self._enqueue(connection, event)

    def abort_subscription(
        self, connection: RealtimeConnection, task_type: str, task_id: UUID
    ) -> None:
        key = (task_type, task_id)
        connection.recovering.pop(key, None)
        connection.subscriptions.discard(key)

    async def publish(self, event: dict[str, object]) -> None:
        try:
            key = (str(event["task_type"]), UUID(str(event["task_id"])))
        except (KeyError, ValueError):
            return
        for connection in tuple(self._connections):
            if key not in connection.subscriptions:
                continue
            if key in connection.recovering:
                buffered = connection.recovering[key]
                if len(buffered) < 64:
                    buffered.append(event)
                else:
                    connection.recovering[key] = [
                        {"type": "resync.required", "reason": "recovery_overflow"}
                    ]
                continue
            self._enqueue(connection, event)

    @staticmethod
    def _event_version(event: dict[str, object]) -> int:
        value = event.get("version")
        return value if type(value) is int else -1

    @staticmethod
    def _enqueue(connection: RealtimeConnection, event: dict[str, object]) -> None:
        try:
            connection.queue.put_nowait(event)
        except asyncio.QueueFull:
            while not connection.queue.empty():
                connection.queue.get_nowait()
            connection.queue.put_nowait(
                {"type": "resync.required", "reason": "slow_consumer"}
            )


class RabbitMqRealtimeConsumer:
    def __init__(
        self,
        url: str,
        exchange: str,
        hub: RealtimeHub,
        *,
        connection_timeout: float = 10,
        heartbeat: int = 60,
        reconnect_interval: float = 5,
    ) -> None:
        if (
            not url
            or not exchange
            or connection_timeout <= 0
            or heartbeat < 10
            or reconnect_interval <= 0
        ):
            raise ValueError("invalid RabbitMQ consumer settings")
        self._url = url
        self._exchange = exchange
        self._hub = hub
        self._connection_timeout = connection_timeout
        self._heartbeat = heartbeat
        self._reconnect_interval = reconnect_interval
        self._connection: AbstractRobustConnection | None = None
        self._queue: AbstractQueue | None = None
        self._tag: str | None = None

    async def start(self) -> None:
        if self._connection is not None:
            return
        connection = await aio_pika.connect_robust(
            configured_rabbitmq_url(
                self._url,
                heartbeat=self._heartbeat,
                reconnect_interval=self._reconnect_interval,
                connection_name="framefetch-server-realtime-gateway",
            ),
            timeout=self._connection_timeout,
        )
        self._connection = connection
        try:
            async with asyncio.timeout(self._connection_timeout):
                channel = await connection.channel()
                await channel.set_qos(prefetch_count=100)
                exchange = await channel.declare_exchange(self._exchange, passive=True)
                queue = await channel.declare_queue(
                    "", exclusive=True, auto_delete=True
                )
                await queue.bind(exchange, routing_key="task.state.changed")
                self._queue = queue
                self._tag = await queue.consume(self._consume)
        except BaseException:
            await asyncio.shield(self.close())
            raise

    async def close(self) -> None:
        if self._queue is not None and self._tag is not None:
            await self._queue.cancel(self._tag)
        self._queue = None
        self._tag = None
        if self._connection is not None:
            await self._connection.close()
        self._connection = None

    async def _consume(self, message: AbstractIncomingMessage) -> None:
        try:
            envelope = EventEnvelope.from_bytes(message.body)
            if envelope.event_type != "task.state.changed":
                raise EventEnvelopeError("unexpected realtime event")
            event: dict[str, object] = {
                "type": "task.updated",
                "event_id": str(envelope.event_id),
                **envelope.payload,
            }
            await self._hub.publish(event)
        except (EventEnvelopeError, TypeError, ValueError):
            await message.nack(requeue=False)
            return
        await message.ack()
