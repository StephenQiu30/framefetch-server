"""Report publication, recovery and artifact lifecycle inside the worker process."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.core.db import create_session_factory
from app.integrations.analysis_report_docx import PythonDocxAnalysisReportRenderer
from app.integrations.messaging import RabbitMqTopology
from app.integrations.object_storage import MinioObjectStorage
from app.repositories.analysis.report_repository import (
    SqlAlchemyAnalysisReportRepository,
)
from app.workers.report.consumer import RabbitMqReportConsumer
from app.workers.report.lifecycle import ReportLifecycleWorker
from app.workers.report.publisher import ReportPublisher
from app.workers.report.sweeper import ReportRecoverySweeper
from sqlalchemy.ext.asyncio import AsyncEngine


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class ReportRuntime:
    consumer: RabbitMqReportConsumer
    sweeper: ReportRecoverySweeper
    lifecycle: ReportLifecycleWorker

    async def serve(self, stop: asyncio.Event) -> None:
        try:
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(self.consumer.run(stop))
                tasks.create_task(self.sweeper.run(stop))
                tasks.create_task(self.lifecycle.run(stop))
        finally:
            await self.consumer.close()

    async def close(self) -> None:
        await self.consumer.close()


def build_runtime(
    settings: Settings, engine: AsyncEngine, *, worker_id: str
) -> ReportRuntime:
    storage = MinioObjectStorage(settings)
    repository = SqlAlchemyAnalysisReportRepository(create_session_factory(engine))
    publisher = ReportPublisher(
        repository,
        storage,
        PythonDocxAnalysisReportRenderer(),
        bucket=settings.minio_bucket,
        max_bytes=settings.analysis_report_max_bytes,
        worker_id=worker_id,
        clock=_utc_now,
    )
    return ReportRuntime(
        consumer=RabbitMqReportConsumer(
            settings.rabbitmq_url,
            RabbitMqTopology(
                settings.rabbitmq_exchange,
                settings.download_queue,
                settings.download_routing_key,
                report_queue=settings.analysis_report_queue,
                report_routing_key=settings.analysis_report_routing_key,
            ),
            publisher,
            connection_timeout=settings.rabbitmq_connection_timeout_seconds,
            prefetch=settings.worker_prefetch,
            heartbeat=settings.rabbitmq_heartbeat_seconds,
            reconnect_interval=settings.rabbitmq_reconnect_interval_seconds,
        ),
        sweeper=ReportRecoverySweeper(repository, _utc_now),
        lifecycle=ReportLifecycleWorker(
            repository,
            storage,
            _utc_now,
            interval=settings.analysis_report_gc_interval_seconds,
            batch_size=settings.analysis_report_gc_batch_size,
            orphan_grace=timedelta(
                seconds=settings.analysis_report_orphan_grace_seconds
            ),
            delete_timeout=settings.artifact_delete_timeout_seconds,
        ),
    )
