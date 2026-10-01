"""Link inspection (Temporal) and downloads (RabbitMQ) inside the worker process."""

from __future__ import annotations

import asyncio
import hashlib
import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.config import Settings
from app.core.db import create_session_factory
from app.core.security.url_cipher import URLCipher
from app.integrations.media_runner import MediaRunnerRouter
from app.integrations.media_runner_factory import media_runner_router
from app.integrations.messaging import RabbitMqTopology
from app.integrations.object_storage import MinioObjectStorage
from app.integrations.readiness import assert_download_execution_schema
from app.integrations.temporal_client import connect_temporal
from app.integrations.thumbnail_storage import MinioThumbnailStorage
from app.integrations.url_security import FernetUrlEnvelope, MediaUrlValidator
from app.repositories.downloads.execution import DownloadExecutionRepository
from app.repositories.downloads.intent_repository import IntentRepository
from app.repositories.downloads.repository import SqlAlchemyDownloadRepository
from app.services.download_execution.models import DownloadExecutionSettings
from app.services.download_execution.service import DownloadExecution
from app.services.downloads.fingerprints import HmacRequestFingerprinter
from app.services.downloads.inspect_media import InspectMedia
from app.services.downloads.thumbnail_use_cases import PersistThumbnail
from app.workers.download.activities import InspectionActivities
from app.workers.download.consumer import RabbitMqDownloadConsumer
from app.workers.download.sweeper import DownloadRecoverySweeper, RecoverySettings
from app.workers.download.thumbnail import ArtifactThumbnailRecovery
from app.workers.download.workflows import InspectionWorkflow
from app.workers.download.workspace import SharedWorkspaceCleaner
from app.workers.runner.provider_registry import configure_provider_instances
from sqlalchemy.ext.asyncio import AsyncEngine
from temporalio.worker import Worker


@dataclass(slots=True)
class DownloadWorkerRuntime:
    consumer: RabbitMqDownloadConsumer
    sweeper: DownloadRecoverySweeper
    storage: MinioObjectStorage
    runner: MediaRunnerRouter
    engine: AsyncEngine
    inspection_activities: InspectionActivities
    temporal_address: str
    temporal_namespace: str

    async def serve(self, stop: asyncio.Event) -> None:
        await _serve(self, stop)

    async def close(self) -> None:
        try:
            await self.consumer.close()
        finally:
            await self.runner.close()


def build_runtime(settings: Settings, engine: AsyncEngine) -> DownloadWorkerRuntime:
    configure_provider_instances(settings.peertube_allowed_instances)
    sessions = create_session_factory(engine)
    raw_repository = SqlAlchemyDownloadRepository(sessions)
    repository = DownloadExecutionRepository(raw_repository)
    workspace_cleaner = SharedWorkspaceCleaner(settings.runner_workspace_root)
    runner = media_runner_router(settings)
    storage = MinioObjectStorage(settings)
    thumbnail_recovery = ArtifactThumbnailRecovery(
        PersistThumbnail(
            raw_repository,
            MinioThumbnailStorage(
                storage,
                max_bytes=settings.download_thumbnail_max_bytes,
            ),
        ),
        ffmpeg_binary=settings.download_thumbnail_ffmpeg_binary,
        timeout_seconds=settings.download_thumbnail_timeout_seconds,
        max_bytes=settings.download_thumbnail_max_bytes,
    )
    execution = DownloadExecution(
        repository=repository,
        runner=runner,
        storage=storage,
        url_cipher=FernetUrlEnvelope(
            URLCipher(settings.url_encryption_key.get_secret_value().encode()),
            key_id=settings.url_encryption_key_id,
        ),
        workspace_cleaner=workspace_cleaner,
        clock=_utc_now,
        settings=DownloadExecutionSettings(
            worker_id=_worker_id(),
            bucket=settings.minio_bucket,
            workspace_root=settings.runner_workspace_root,
            lease_for=timedelta(seconds=settings.job_lease_seconds),
            heartbeat_interval=settings.heartbeat_interval_seconds,
            max_file_size_bytes=settings.max_file_size_bytes,
        ),
        thumbnail_recovery=thumbnail_recovery,
    )
    topology = RabbitMqTopology(
        settings.rabbitmq_exchange,
        settings.download_queue,
        settings.download_routing_key,
    )
    intents = IntentRepository(sessions)
    envelope = FernetUrlEnvelope(
        URLCipher(settings.url_encryption_key.get_secret_value().encode()),
        key_id=settings.url_encryption_key_id,
    )
    inspection_activities = InspectionActivities(
        intents,
        InspectMedia(
            repository=raw_repository,
            runner=runner,
            url_validator=MediaUrlValidator(),
            url_cipher=envelope,
            fingerprinter=HmacRequestFingerprinter(
                settings.request_fingerprint_secret.get_secret_value().encode()
            ),
            now=_utc_now,
            new_id=uuid4,
            inspection_ttl=timedelta(seconds=settings.inspection_ttl_seconds),
            max_duration_seconds=settings.max_video_duration_seconds,
        ),
        envelope,
        clock=_utc_now,
    )
    return DownloadWorkerRuntime(
        inspection_activities=inspection_activities,
        temporal_address=settings.temporal_address,
        temporal_namespace=settings.temporal_namespace,
        consumer=RabbitMqDownloadConsumer(
            settings.rabbitmq_url,
            topology,
            execution,
            prefetch=settings.download_worker_threads,
            workers=settings.download_worker_threads,
            connection_timeout=settings.rabbitmq_connection_timeout_seconds,
            heartbeat=settings.rabbitmq_heartbeat_seconds,
            reconnect_interval=settings.rabbitmq_reconnect_interval_seconds,
        ),
        sweeper=DownloadRecoverySweeper(
            raw_repository,
            _utc_now,
            RecoverySettings(
                interval=min(5.0, settings.heartbeat_interval_seconds),
                batch_size=100,
                queued_stale_after=timedelta(
                    seconds=settings.download_queued_recovery_seconds
                ),
                workspace_gc_after=timedelta(
                    seconds=settings.download_workspace_gc_seconds
                ),
            ),
            workspace_cleaner,
        ),
        storage=storage,
        runner=runner,
        engine=engine,
    )


async def _serve(runtime: DownloadWorkerRuntime, stop: asyncio.Event) -> None:
    await assert_download_execution_schema(runtime.engine)
    client = await connect_temporal(
        runtime.temporal_address, runtime.temporal_namespace
    )
    inspection_worker = Worker(
        client,
        task_queue="ff-inspect",
        workflows=[InspectionWorkflow],
        activities=[
            runtime.inspection_activities.resolve,
        ],
        max_concurrent_activities=2,
        graceful_shutdown_timeout=timedelta(seconds=30),
        max_heartbeat_throttle_interval=timedelta(seconds=5),
    )
    consumer = asyncio.create_task(runtime.consumer.run(stop))
    intent_worker = asyncio.create_task(inspection_worker.run())
    sweeper = asyncio.create_task(runtime.sweeper.run(stop))
    stop_wait = asyncio.create_task(stop.wait())
    tasks = (consumer, intent_worker, sweeper)
    try:
        await asyncio.wait(
            {*tasks, stop_wait},
            return_when=asyncio.FIRST_COMPLETED,
        )
        stop.set()
        await asyncio.gather(runtime.consumer.close(), inspection_worker.shutdown())
        await asyncio.gather(*tasks, return_exceptions=True)
        for task in tasks:
            if task.cancelled():
                continue
            failure = task.exception()
            if failure is not None:
                raise failure
    finally:
        stop_wait.cancel()
        await asyncio.gather(stop_wait, return_exceptions=True)


def _worker_id() -> str:
    hostname = socket.gethostname()
    digest = hashlib.sha256(hostname.encode()).hexdigest()[:12]
    return f"download-{hostname[:64]}-{digest}-{os.getpid()}"


def _utc_now() -> datetime:
    return datetime.now(UTC)
