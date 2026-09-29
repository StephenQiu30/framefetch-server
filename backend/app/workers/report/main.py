"""Run with: python -m app.workers.report.main."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings_for_role
from app.core.db import create_engine, create_session_factory
from app.integrations.analysis_report_docx import PythonDocxAnalysisReportRenderer
from app.integrations.messaging import RabbitMqTopology
from app.integrations.object_storage import MinioObjectStorage
from app.repositories.analysis.report_repository import (
    SqlAlchemyAnalysisReportRepository,
)
from app.workers.analysis.utilities import install_signal_handlers, worker_id
from app.workers.report.consumer import RabbitMqReportConsumer
from app.workers.report.lifecycle import ReportLifecycleWorker
from app.workers.report.publisher import ReportPublisher
from app.workers.report.sweeper import ReportRecoverySweeper


async def run() -> None:
    settings = get_settings_for_role("report-worker")
    engine = create_engine(settings.database_url)
    storage = MinioObjectStorage(settings)
    topology = RabbitMqTopology(
        settings.rabbitmq_exchange,
        settings.download_queue,
        settings.download_routing_key,
        report_queue=settings.analysis_report_queue,
        report_routing_key=settings.analysis_report_routing_key,
    )
    repository = SqlAlchemyAnalysisReportRepository(create_session_factory(engine))
    publisher = ReportPublisher(
        repository,
        storage,
        PythonDocxAnalysisReportRenderer(),
        bucket=settings.minio_bucket,
        max_bytes=settings.analysis_report_max_bytes,
        worker_id=worker_id().replace("analysis-", "report-", 1),
        clock=lambda: datetime.now(UTC),
    )
    consumer = RabbitMqReportConsumer(
        settings.rabbitmq_url,
        topology,
        publisher,
        connection_timeout=settings.rabbitmq_connection_timeout_seconds,
        prefetch=settings.worker_prefetch,
        heartbeat=settings.rabbitmq_heartbeat_seconds,
        reconnect_interval=settings.rabbitmq_reconnect_interval_seconds,
    )
    stop = asyncio.Event()
    install_signal_handlers(stop)
    try:
        consumer_task = asyncio.create_task(consumer.run(stop))
        sweeper_task = asyncio.create_task(
            ReportRecoverySweeper(repository, lambda: datetime.now(UTC)).run(stop)
        )
        lifecycle_task = asyncio.create_task(
            ReportLifecycleWorker(
                repository,
                storage,
                lambda: datetime.now(UTC),
                interval=settings.analysis_report_gc_interval_seconds,
                batch_size=settings.analysis_report_gc_batch_size,
                orphan_grace=timedelta(
                    seconds=settings.analysis_report_orphan_grace_seconds
                ),
                delete_timeout=settings.artifact_delete_timeout_seconds,
            ).run(stop)
        )
        stop_task = asyncio.create_task(stop.wait())
        await asyncio.wait(
            {consumer_task, sweeper_task, lifecycle_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        stop.set()
        await asyncio.gather(
            consumer_task,
            sweeper_task,
            lifecycle_task,
            return_exceptions=True,
        )
    finally:
        await consumer.close()
        await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
