from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Protocol
from uuid import UUID

import aio_pika
from aio_pika.abc import (
    AbstractIncomingMessage,
    AbstractQueue,
    AbstractRobustConnection,
)
from app.integrations.messaging.connection import configured_rabbitmq_url
from app.integrations.messaging.topology import RabbitMqTopology
from app.services.imports.models import ImportDisposition
from app.services.imports.rules.enums import ContentKind
from app.workers.imports.message import (
    ImportMessageError,
    parse_import_verify_requested,
)


class ImportHandler(Protocol):
    async def execute(
        self,
        resource_id: UUID,
        content_kind: ContentKind,
        attempt: int,
        expected_version: int,
    ) -> ImportDisposition: ...


class Delivery(Protocol):
    body: bytes
    redelivered: bool | None

    async def ack(self) -> None: ...

    async def nack(self, *, requeue: bool) -> None: ...


async def process_delivery(message: Delivery, handler: ImportHandler) -> None:
    try:
        requested = parse_import_verify_requested(message.body)
    except ImportMessageError:
        await message.nack(requeue=False)
        return
    try:
        disposition = await handler.execute(
            requested.resource_id,
            requested.content_kind,
            requested.attempt,
            requested.version,
        )
    except asyncio.CancelledError:
        with suppress(Exception):
            await asyncio.shield(message.nack(requeue=True))
        raise
    except Exception:
        await message.nack(requeue=not bool(message.redelivered))
        return
    if disposition is ImportDisposition.ACK:
        await message.ack()
    else:
        await message.nack(requeue=not bool(message.redelivered))


class RabbitMqImportConsumer:
    def __init__(
        self,
        url: str,
        topology: RabbitMqTopology,
        handler: ImportHandler,
        *,
        prefetch: int,
        connection_timeout: float = 10,
        heartbeat: int = 60,
        reconnect_interval: float = 5,
    ) -> None:
        if (
            not url
            or prefetch < 1
            or connection_timeout <= 0
            or heartbeat < 10
            or reconnect_interval <= 0
        ):
            raise ValueError("invalid RabbitMQ import consumer settings")
        self._url = url
        self._topology = topology
        self._handler = handler
        self._prefetch = prefetch
        self._connection_timeout = connection_timeout
        self._heartbeat = heartbeat
        self._reconnect_interval = reconnect_interval
        self._connection: AbstractRobustConnection | None = None
        self._queue: AbstractQueue | None = None
        self._consumer_tag: str | None = None
        self._active: set[asyncio.Task[object]] = set()

    async def start(self) -> None:
        if self._connection is not None:
            return
        connection = await aio_pika.connect_robust(
            configured_rabbitmq_url(
                self._url,
                heartbeat=self._heartbeat,
                reconnect_interval=self._reconnect_interval,
                connection_name="framefetch-server-import-worker",
            ),
            timeout=self._connection_timeout,
        )
        self._connection = connection
        try:
            async with asyncio.timeout(self._connection_timeout):
                channel = await connection.channel()
                await channel.set_qos(prefetch_count=self._prefetch)
                binding = self._topology.imports
                queue = await channel.declare_queue(binding.queue, passive=True)
                self._queue = queue
                self._consumer_tag = await queue.consume(self._consume)
        except BaseException:
            await asyncio.shield(self.close())
            raise

    async def run(self, stop: asyncio.Event) -> None:
        await self.start()
        await stop.wait()

    async def close(self) -> None:
        queue, tag = self._queue, self._consumer_tag
        self._queue = None
        self._consumer_tag = None
        if queue is not None and tag is not None:
            with suppress(Exception):
                await queue.cancel(tag)
        active = tuple(self._active)
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        connection = self._connection
        self._connection = None
        if connection is not None:
            await connection.close()

    async def _consume(self, message: AbstractIncomingMessage) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._active.add(task)
        try:
            await process_delivery(message, self._handler)
        finally:
            if task is not None:
                self._active.discard(task)
