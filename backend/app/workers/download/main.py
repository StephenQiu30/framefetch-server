"""Run with: python -m app.workers.download.main."""

from __future__ import annotations

import asyncio
import hashlib
import os
import signal
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.config import Settings, get_settings_for_role
from app.core.db import create_engine, create_session_factory
from app.core.security.url_cipher import URLCipher
from app.integrations.media_runner import MediaRunnerRouter
from app.integrations.media_runner_factory import media_runner_router
from app.integrations.messaging import RabbitMqTopology
from app.integrations.object_storage import MinioObjectStorage
from app.integrations.readiness import assert_download_execution_schema
from app.integrations.site_session_catalog import SiteSessionRoutes
from app.integrations.thumbnail_storage import MinioThumbnailStorage
from app.integrations.url_security import FernetUrlEnvelope, MediaUrlValidator
from app.repositories.downloads.execution import DownloadExecutionRepository
from app.repositories.downloads.intent_repository import IntentRepository
from app.repositories.downloads.repository import SqlAlchemyDownloadRepository
from app.repositories.providers.guest_contexts import GuestContexts
from app.repositories.providers.route_cooldowns import SqlAlchemyProviderRouteCooldowns
from app.repositories.providers.site_sessions import SiteSessionStates
from app.services.download_execution.models import DownloadExecutionSettings
from app.services.download_execution.service import DownloadExecution
from app.services.downloads.fingerprints import HmacRequestFingerprinter
from app.services.downloads.inspect_media import InspectMedia
from app.services.downloads.intent_execution import IntentExecution
from app.services.downloads.thumbnail_use_cases import PersistThumbnail
from app.services.provider_route_admission import ProviderRouteAdmission
from app.workers.download.consumer import RabbitMqDownloadConsumer
from app.workers.download.sweeper import DownloadRecoverySweeper, RecoverySettings
from app.workers.download.thumbnail import ArtifactThumbnailRecovery
from app.workers.download.workspace import SharedWorkspaceCleaner
from app.workers.runner.provider_registry import configure_provider_instances
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(slots=True)
class DownloadWorkerRuntime:
    consumer: RabbitMqDownloadConsumer
    sweeper: DownloadRecoverySweeper
    storage: MinioObjectStorage
    runner: MediaRunnerRouter
    engine: AsyncEngine
    intent_consumer: RabbitMqDownloadConsumer

    async def close(self) -> None:
        try:
            await asyncio.gather(self.consumer.close(), self.intent_consumer.close())
        finally:
            try:
                await self.runner.close()
            finally:
                await self.engine.dispose()


def build_runtime(settings: Settings) -> DownloadWorkerRuntime:
    configure_provider_instances(settings.peertube_allowed_instances)
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    raw_repository = SqlAlchemyDownloadRepository(sessions)
    repository = DownloadExecutionRepository(raw_repository)
    workspace_cleaner = SharedWorkspaceCleaner(settings.runner_workspace_root)
    session_routes = SiteSessionRoutes(SiteSessionStates(sessions))
    runner = media_runner_router(
        settings,
        ProviderRouteAdmission(SqlAlchemyProviderRouteCooldowns(sessions)),
        reject_guest=GuestContexts(sessions).reject,
        session_routes=session_routes,
    )
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
    intent_execution = IntentExecution(
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
        worker_id=_worker_id(),
        clock=_utc_now,
    )
    return DownloadWorkerRuntime(
        intent_consumer=RabbitMqDownloadConsumer(
            settings.rabbitmq_url,
            topology,
            intent_execution,
            prefetch=2,
            workers=2,
            intent=True,
            connection_timeout=settings.rabbitmq_connection_timeout_seconds,
            heartbeat=settings.rabbitmq_heartbeat_seconds,
            reconnect_interval=settings.rabbitmq_reconnect_interval_seconds,
        ),
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
            intents,
        ),
        storage=storage,
        runner=runner,
        engine=engine,
    )


async def run() -> None:
    runtime = build_runtime(get_settings_for_role("download-worker"))
    stop = asyncio.Event()
    _install_signal_handlers(stop)
    try:
        await _serve(runtime, stop)
    finally:
        stop.set()
        await asyncio.shield(runtime.close())


async def _serve(runtime: DownloadWorkerRuntime, stop: asyncio.Event) -> None:
    await assert_download_execution_schema(runtime.engine)
    consumer = asyncio.create_task(runtime.consumer.run(stop))
    intent_consumer = asyncio.create_task(runtime.intent_consumer.run(stop))
    sweeper = asyncio.create_task(runtime.sweeper.run(stop))
    stop_wait = asyncio.create_task(stop.wait())
    tasks = (consumer, intent_consumer, sweeper)
    try:
        await asyncio.wait(
            {*tasks, stop_wait},
            return_when=asyncio.FIRST_COMPLETED,
        )
        stop.set()
        await asyncio.gather(runtime.consumer.close(), runtime.intent_consumer.close())
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


def _install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for requested_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(requested_signal, stop.set)
        except NotImplementedError:
            pass


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
