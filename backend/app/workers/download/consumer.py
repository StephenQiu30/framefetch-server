from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any, Protocol, cast
from uuid import UUID

import aio_pika
from aio_pika import ExchangeType
from aio_pika.abc import (
    AbstractIncomingMessage,
    AbstractQueue,
    AbstractRobustConnection,
)
from app.integrations.messaging import RabbitMqTopology, configured_rabbitmq_url
from app.services.download_execution.models import ExecutionDisposition
from app.workers.download.message import (
    DownloadMessageError,
    parse_download_requested,
)
from app.workers.download.pool import AsyncWorkerPool

_log = logging.getLogger(__name__)
_MAX_DELIVERY_ATTEMPTS = 2


class DownloadHandler(Protocol):
    async def execute(self, job_id: UUID) -> ExecutionDisposition: ...


class Delivery(Protocol):
    body: bytes
    redelivered: bool | None

    async def ack(self) -> None: ...

    async def nack(self, *, requeue: bool) -> None: ...


async def process_delivery(message: Delivery, handler: DownloadHandler) -> None:
    delivery_attempt = _delivery_attempt(message)
    replay_count = _replay_count(message)
    try:
        resource_id = parse_download_requested(message.body).job_id
    except DownloadMessageError:
        await _settle(
            message,
            requeue=False,
            delivery_attempt=delivery_attempt,
            replay_count=replay_count,
            outcome="dead_lettered",
        )
        return
    try:
        result = await handler.execute(resource_id)
    except asyncio.CancelledError:
        with suppress(Exception):
            await asyncio.shield(message.nack(requeue=True))
        raise
    except Exception:
        await _settle(
            message,
            requeue=not bool(message.redelivered),
            delivery_attempt=delivery_attempt,
            replay_count=replay_count,
            outcome="requeued" if not message.redelivered else "dead_lettered",
        )
        return
    if result is ExecutionDisposition.ACK:
        await message.ack()
        _log.info(
            "download delivery acknowledged",
            extra=_observation(delivery_attempt, replay_count, "acknowledged"),
        )
    else:
        await _settle(
            message,
            requeue=not bool(message.redelivered),
            delivery_attempt=delivery_attempt,
            replay_count=replay_count,
            outcome="requeued" if not message.redelivered else "dead_lettered",
        )


async def _settle(
    message: Delivery,
    *,
    requeue: bool,
    delivery_attempt: int,
    replay_count: int,
    outcome: str,
) -> None:
    _log.warning(
        "download delivery %s",
        outcome,
        extra=_observation(delivery_attempt, replay_count, outcome),
    )
    await message.nack(requeue=requeue)


def _observation(
    delivery_attempt: int, replay_count: int, outcome: str
) -> dict[str, object]:
    return {
        "delivery_attempt": delivery_attempt,
        "delivery_attempt_budget": _MAX_DELIVERY_ATTEMPTS,
        "delivery_budget_remaining": max(0, _MAX_DELIVERY_ATTEMPTS - delivery_attempt),
        "dlq_replay_count": replay_count,
        "delivery_outcome": outcome,
    }


def _delivery_attempt(message: Delivery) -> int:
    return 2 if bool(message.redelivered) else 1


def _replay_count(message: Delivery) -> int:
    value = (getattr(message, "headers", None) or {}).get("x-replay-count", 0)
    return value if type(value) is int and 0 <= value <= 3 else 0


async def _declare_download_topology(
    channel: Any, topology: RabbitMqTopology
) -> AbstractQueue:
    """Declare the download queue and its DLX so startup verifies the contract."""
    binding = topology.download
    exchange = await channel.declare_exchange(
        topology.exchange, type=ExchangeType.TOPIC, durable=True
    )
    dead_exchange = await channel.declare_exchange(
        topology.dead_exchange, type=ExchangeType.TOPIC, durable=True
    )
    queue = await channel.declare_queue(
        binding.queue,
        durable=True,
        arguments={
            "x-message-ttl": binding.message_ttl_ms,
            "x-max-length": binding.max_length,
            "x-dead-letter-exchange": topology.dead_exchange,
            "x-dead-letter-routing-key": binding.dead_routing_key,
        },
    )
    dead_queue = await channel.declare_queue(
        binding.dead_queue,
        durable=True,
        arguments={"x-max-length": binding.max_length},
    )
    await queue.bind(exchange, routing_key=binding.routing_key)
    await dead_queue.bind(dead_exchange, routing_key=binding.dead_routing_key)
    return cast(AbstractQueue, queue)


class RabbitMqDownloadConsumer:
    def __init__(
        self,
        url: str,
        topology: RabbitMqTopology,
        handler: DownloadHandler,
        *,
        prefetch: int,
        workers: int | None = None,
        connection_timeout: float = 10,
        heartbeat: int = 60,
        reconnect_interval: float = 5,
    ) -> None:
        worker_count = prefetch if workers is None else workers
        if (
            not url
            or prefetch < 1
            or worker_count < 1
            or connection_timeout <= 0
            or heartbeat < 10
            or reconnect_interval <= 0
        ):
            raise ValueError("invalid RabbitMQ consumer settings")
        self._url = url
        self._topology = topology
        self._handler = handler
        self._prefetch = prefetch
        self._pool = AsyncWorkerPool(
            self._consume_delivery,
            workers=worker_count,
        )
        self._connection_timeout = connection_timeout
        self._heartbeat = heartbeat
        self._reconnect_interval = reconnect_interval
        self._connection: AbstractRobustConnection | None = None
        self._queue: AbstractQueue | None = None
        self._consumer_tag: str | None = None

    async def start(self) -> None:
        if self._connection is not None:
            return
        connection = await aio_pika.connect_robust(
            configured_rabbitmq_url(
                self._url,
                heartbeat=self._heartbeat,
                reconnect_interval=self._reconnect_interval,
                connection_name="video-server-download-worker",
            ),
            timeout=self._connection_timeout,
        )
        self._connection = connection
        try:
            async with asyncio.timeout(self._connection_timeout):
                channel = await connection.channel()
                await channel.set_qos(prefetch_count=self._prefetch)
                queue = await _declare_download_topology(channel, self._topology)
                self._queue = queue
                await self._pool.start()
                self._consumer_tag = await queue.consume(self._consume)
        except BaseException:
            await asyncio.shield(self.close())
            raise

    async def run(self, stop: asyncio.Event) -> None:
        await self.start()
        await stop.wait()

    async def close(self) -> None:
        queue, consumer_tag = self._queue, self._consumer_tag
        self._queue = None
        self._consumer_tag = None
        if queue is not None and consumer_tag is not None:
            with suppress(Exception):
                await queue.cancel(consumer_tag)
        await self._pool.close()
        connection = self._connection
        self._connection = None
        if connection is not None:
            await connection.close()

    async def _consume(self, message: AbstractIncomingMessage) -> None:
        await self._pool.submit(message)

    async def _consume_delivery(self, message: AbstractIncomingMessage) -> None:
        await process_delivery(message, self._handler)
