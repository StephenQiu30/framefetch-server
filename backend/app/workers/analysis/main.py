"""Internal worker process launched by the canonical analysis Agent CLI."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from functools import partial

from app.core.config import Settings, get_settings_for_role
from app.core.db import create_engine, create_session_factory
from app.core.security.ai_provider_cipher import FernetAiProviderSecretCipher
from app.core.security.url_cipher import URLCipher
from app.integrations.object_storage import MinioObjectStorage
from app.integrations.temporal_client import connect_temporal
from app.repositories.ai_provider_repository import SqlAlchemyAiProviderRepository
from app.repositories.analysis.worker_registry import (
    ANALYSIS_MESSAGE_SCHEMA_VERSION,
    SqlAlchemyAnalysisWorkerRegistry,
)
from app.repositories.creation import CreationRepository
from app.workers.analysis.agent_lock import (
    AnalysisAgentAlreadyRunning,
    analysis_agent_process_lock,
)
from app.workers.analysis.artifacts import LocalAnalysisArtifactLoader
from app.workers.analysis.creation_activities import CreationActivities
from app.workers.analysis.creation_workflow import CreationWorkflow
from app.workers.analysis.heartbeat import AnalysisWorkerHeartbeat
from app.workers.analysis.providers import ConfiguredAnalyzerResolver
from app.workers.analysis.utilities import utc_now, worker_id
from app.workers.supervision import install_signal_handlers, run_resilient
from sqlalchemy.ext.asyncio import AsyncEngine
from temporalio.worker import Worker

SKILL_TASK_QUEUE = "ff-skill"


@dataclass(slots=True)
class AnalysisWorkerRuntime:
    creation: CreationActivities
    temporal_address: str
    temporal_namespace: str
    heartbeat: AnalysisWorkerHeartbeat
    storage: MinioObjectStorage
    loader: LocalAnalysisArtifactLoader
    engine: AsyncEngine
    resolver: ConfiguredAnalyzerResolver

    async def close(self) -> None:
        try:
            await self.heartbeat.close()
        finally:
            await self.engine.dispose()


def build_runtime(settings: Settings) -> AnalysisWorkerRuntime:
    minio_access_key, minio_secret_key = settings.analysis_minio_credentials()
    host_settings = settings.model_copy(
        update={
            "database_url": settings.analysis_database_url,
            "minio_endpoint": settings.analysis_minio_endpoint,
            "minio_access_key": minio_access_key,
            "minio_secret_key": minio_secret_key,
        }
    )
    engine = create_engine(host_settings.database_url)
    sessions = create_session_factory(engine)
    resolver = ConfiguredAnalyzerResolver(
        settings,
        SqlAlchemyAiProviderRepository(sessions),
        FernetAiProviderSecretCipher(
            URLCipher(settings.url_encryption_key.get_secret_value().encode()),
            key_id=settings.url_encryption_key_id,
        ),
    )
    runtime_worker_id = worker_id()
    worker_registry = SqlAlchemyAnalysisWorkerRegistry(
        sessions,
        expected_app_version=settings.app_version,
        expected_message_schema_version=ANALYSIS_MESSAGE_SCHEMA_VERSION,
        stale_after=timedelta(seconds=settings.analysis_worker_stale_seconds),
    )
    storage = MinioObjectStorage(host_settings)
    loader = LocalAnalysisArtifactLoader(
        storage,
        workspace_root=settings.analysis_workspace_root,
        bucket=settings.minio_bucket,
        max_source_bytes=settings.max_file_size_bytes,
    )
    return AnalysisWorkerRuntime(
        creation=CreationActivities(
            CreationRepository(sessions), resolver, loader, settings
        ),
        temporal_address=settings.temporal_address,
        temporal_namespace=settings.temporal_namespace,
        heartbeat=AnalysisWorkerHeartbeat(
            worker_registry,
            worker_id=runtime_worker_id,
            app_version=settings.app_version,
            message_schema_version=ANALYSIS_MESSAGE_SCHEMA_VERSION,
            interval=settings.analysis_worker_heartbeat_seconds,
            clock=utc_now,
        ),
        storage=storage,
        loader=loader,
        engine=engine,
        resolver=resolver,
    )


async def run(settings: Settings | None = None) -> None:
    runtime = build_runtime(settings or get_settings_for_role("analysis-worker"))
    stop = asyncio.Event()
    install_signal_handlers(stop)
    try:
        await runtime.loader.prepare_root()
        # Text formatting and card preparation remain usable without a model
        # profile; each model task performs its own readiness check.
        await _serve(runtime, stop)
    finally:
        stop.set()
        await asyncio.shield(runtime.close())


async def _serve(runtime: AnalysisWorkerRuntime, stop: asyncio.Event) -> None:
    tasks = (
        asyncio.create_task(
            run_resilient("skill", partial(_run_skill_worker, runtime), stop),
            name="analysis-skill-worker",
        ),
        asyncio.create_task(
            run_resilient("heartbeat", runtime.heartbeat.run, stop),
            name="analysis-heartbeat",
        ),
    )
    try:
        await stop.wait()
    finally:
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _run_skill_worker(
    runtime: AnalysisWorkerRuntime, stop: asyncio.Event
) -> None:
    """Serve bounded activities; CreationActivities reserves one model slot."""
    client = await connect_temporal(
        runtime.temporal_address, runtime.temporal_namespace
    )
    worker = Worker(
        client,
        task_queue=SKILL_TASK_QUEUE,
        workflows=[CreationWorkflow],
        activities=[
            runtime.creation.run,
            runtime.creation.reconcile,
        ],
        max_concurrent_activities=8,
        graceful_shutdown_timeout=timedelta(seconds=30),
        max_heartbeat_throttle_interval=timedelta(seconds=5),
    )
    running = asyncio.create_task(worker.run())
    stopped = asyncio.create_task(stop.wait())
    try:
        await asyncio.wait({running, stopped}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stopped.cancel()
        if not running.done():
            await worker.shutdown()
        await running


def main(settings: Settings | None = None) -> None:
    try:
        with analysis_agent_process_lock():
            asyncio.run(run(settings))
    except AnalysisAgentAlreadyRunning as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
