"""RabbitMQ consumer for isolated report publication work."""

from __future__ import annotations

import asyncio
from contextlib import suppress

import aio_pika
from aio_pika.abc import (
    AbstractIncomingMessage,
    AbstractQueue,
    AbstractRobustConnection,
)
from app.integrations.messaging.connection import configured_rabbitmq_url
from app.integrations.messaging.topology import RabbitMqTopology
from app.workers.report.message import ReportMessageError, parse_report_requested
from app.workers.report.publisher import ReportPublisher


async def process_delivery(
    message: AbstractIncomingMessage, publisher: ReportPublisher
) -> None:
    try:
        requested = parse_report_requested(message.body)
    except ReportMessageError:
        await message.nack(requeue=False)
        return
    try:
        complete = await publisher.execute(requested)
    except asyncio.CancelledError:
        with suppress(Exception):
            await asyncio.shield(message.nack(requeue=True))
        raise
    except Exception:
        complete = False
    if complete:
        await message.ack()
    else:
        await message.nack(requeue=not bool(message.redelivered))


class RabbitMqReportConsumer:
    def __init__(
        self,
        url: str,
        topology: RabbitMqTopology,
        publisher: ReportPublisher,
        *,
        connection_timeout: float = 10,
        prefetch: int = 2,
        heartbeat: int = 60,
        reconnect_interval: float = 5,
    ) -> None:
        if (
            not url
            or connection_timeout <= 0
            or prefetch < 1
            or heartbeat < 10
            or reconnect_interval <= 0
        ):
            raise ValueError("invalid RabbitMQ consumer settings")
        self._url = url
        self._topology = topology
        self._publisher = publisher
        self._connection_timeout = connection_timeout
        self._prefetch = prefetch
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
                connection_name="framefetch-server-report-worker",
            ),
            timeout=self._connection_timeout,
        )
        self._connection = connection
        try:
            async with asyncio.timeout(self._connection_timeout):
                channel = await connection.channel()
                await channel.set_qos(prefetch_count=self._prefetch)
                binding = self._topology.report
                queue = await channel.declare_queue(binding.queue, passive=True)
                self._queue = queue
                self._tag = await queue.consume(self._consume)
        except BaseException:
            await asyncio.shield(self.close())
            raise

    async def run(self, stop: asyncio.Event) -> None:
        await self.start()
        await stop.wait()

    async def close(self) -> None:
        if self._queue is not None and self._tag is not None:
            with suppress(Exception):
                await self._queue.cancel(self._tag)
        self._queue = None
        self._tag = None
        if self._connection is not None:
            await self._connection.close()
        self._connection = None

    async def _consume(self, message: AbstractIncomingMessage) -> None:
        await process_delivery(message, self._publisher)
