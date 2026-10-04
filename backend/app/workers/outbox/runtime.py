"""Outbox dispatch and operation-log retention inside the worker process."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.core.db import create_session_factory
from app.integrations.media_runner import MediaRunnerHttpClient
from app.integrations.media_runner_factory import session_media_runner
from app.integrations.messaging.rabbitmq import RabbitMqPublisher
from app.integrations.messaging.topology import RabbitMqTopology
from app.integrations.temporal_client import CommandPublisher
from app.repositories.analysis.repository import SqlAlchemyAnalysisRepository
from app.repositories.downloads.intent_repository import IntentRepository
from app.repositories.operation_logs import OperationLogStore
from app.repositories.outbox_repository import SqlAlchemyOutboxRepository
from app.workers.outbox.loop import OutboxLoopSettings, OutboxPublisherLoop
from app.workers.outbox.operation_log_retention import OperationLogRetention
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(slots=True)
class OutboxRuntime:
    runner: MediaRunnerHttpClient
    publisher: RabbitMqPublisher
    loop: OutboxPublisherLoop
    retention: OperationLogRetention

    async def serve(self, stop: asyncio.Event) -> None:
        await self.publisher.start()
        try:
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(self.loop.run(stop))
                tasks.create_task(self.retention.run(stop))
        finally:
            await self.publisher.close()

    async def close(self) -> None:
        await self.publisher.close()
        await self.runner.close()


def build_runtime(
    settings: Settings, engine: AsyncEngine, *, publisher_id: str
) -> OutboxRuntime:
    sessions = create_session_factory(engine)
    runner = session_media_runner(settings)
    publisher = RabbitMqPublisher(
        settings.rabbitmq_url,
        RabbitMqTopology(
            exchange=settings.rabbitmq_exchange,
            download_queue=settings.download_queue,
            download_routing_key=settings.download_routing_key,
            report_queue=settings.analysis_report_queue,
            report_routing_key=settings.analysis_report_routing_key,
            import_queue=settings.import_queue,
            import_routing_key=settings.import_routing_key,
        ),
        connection_timeout=settings.rabbitmq_connection_timeout_seconds,
        publish_timeout=settings.rabbitmq_publish_timeout_seconds,
        heartbeat=settings.rabbitmq_heartbeat_seconds,
        reconnect_interval=settings.rabbitmq_reconnect_interval_seconds,
    )
    return OutboxRuntime(
        runner=runner,
        publisher=publisher,
        loop=OutboxPublisherLoop(
            repository=SqlAlchemyOutboxRepository(sessions),
            publisher=CommandPublisher(
                publisher,
                IntentRepository(sessions),
                address=settings.temporal_address,
                namespace=settings.temporal_namespace,
                cancel_inspection=runner.cancel,
                analyses=SqlAlchemyAnalysisRepository(sessions),
                analysis_timeout_seconds=settings.analysis_timeout_seconds,
            ),
            publisher_id=publisher_id,
            clock=lambda: datetime.now(UTC),
            settings=OutboxLoopSettings(
                batch_size=settings.outbox_batch_size,
                claim_lease=timedelta(seconds=settings.job_lease_seconds),
                poll_interval=settings.outbox_poll_interval_seconds,
            ),
        ),
        retention=OperationLogRetention(
            OperationLogStore(sessions),
            clock=lambda: datetime.now(UTC),
            retention=timedelta(days=settings.operation_log_retention_days),
            interval=settings.operation_log_purge_interval_seconds,
            batch_size=settings.operation_log_purge_batch_size,
        ),
    )
