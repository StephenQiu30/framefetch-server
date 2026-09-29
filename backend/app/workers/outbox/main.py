"""Run with: python -m app.workers.outbox.main."""

from __future__ import annotations

import asyncio
import hashlib
import os
import signal
import socket
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings_for_role
from app.core.db import create_engine, create_session_factory
from app.integrations.messaging import RabbitMqPublisher, RabbitMqTopology
from app.integrations.temporal_client import CommandPublisher
from app.repositories.analysis.repository import SqlAlchemyAnalysisRepository
from app.repositories.downloads.intent_repository import IntentRepository
from app.repositories.operation_logs import OperationLogStore
from app.repositories.outbox_repository import SqlAlchemyOutboxRepository
from app.workers.outbox.loop import OutboxLoopSettings, OutboxPublisherLoop
from app.workers.outbox.operation_log_retention import OperationLogRetention


def _publisher_id() -> str:
    hostname = socket.gethostname()
    digest = hashlib.sha256(hostname.encode()).hexdigest()[:12]
    return f"outbox-{hostname[:80]}-{digest}-{os.getpid()}"


async def run() -> None:
    settings = get_settings_for_role("outbox")
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    repository = SqlAlchemyOutboxRepository(sessions)
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
    publisher_loop = OutboxPublisherLoop(
        repository=repository,
        publisher=CommandPublisher(
            publisher,
            IntentRepository(sessions),
            SqlAlchemyAnalysisRepository(sessions),
            address=settings.temporal_address,
            namespace=settings.temporal_namespace,
        ),
        publisher_id=_publisher_id(),
        clock=lambda: datetime.now(UTC),
        settings=OutboxLoopSettings(
            batch_size=settings.outbox_batch_size,
            claim_lease=timedelta(seconds=settings.job_lease_seconds),
            poll_interval=settings.outbox_poll_interval_seconds,
        ),
    )
    retention = OperationLogRetention(
        OperationLogStore(sessions),
        clock=lambda: datetime.now(UTC),
        retention=timedelta(days=settings.operation_log_retention_days),
        interval=settings.operation_log_purge_interval_seconds,
        batch_size=settings.operation_log_purge_batch_size,
    )
    stop = asyncio.Event()
    event_loop = asyncio.get_running_loop()
    try:
        for requested_signal in (signal.SIGINT, signal.SIGTERM):
            try:
                event_loop.add_signal_handler(requested_signal, stop.set)
            except NotImplementedError:
                pass
        await publisher.start()
        retention_task = asyncio.create_task(
            retention.run(stop), name="operation-log-retention"
        )
        try:
            await publisher_loop.run(stop)
        finally:
            stop.set()
            await retention_task
    finally:
        try:
            await publisher.close()
        finally:
            await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
