from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.integrations.media_runner_models import RunnerArtifact, RunnerProgress
from app.services.download_execution.models import DownloadExecutionSettings
from app.services.download_execution.service import DownloadExecution
from app.services.downloads.inspection_models import EncryptedUrl
from app.services.downloads.plans import plan_to_documents
from app.services.downloads.rules.enums import (
    AudioCodecFamily,
    CompatibilityProfile,
    ContainerPreference,
    DownloadStage,
    DynamicRange,
    FpsBucket,
    VideoCodecFamily,
)
from app.services.downloads.rules.formats import DownloadPlan, ProviderHints
from app.services.provider_types import ProviderAccessContextRef, ProviderAccessMode

NOW = datetime(2026, 8, 6, 8, tzinfo=UTC)


class FakeRepository:
    def __init__(self, job_id: UUID) -> None:
        self.job_id = job_id
        self.claimed = True
        self.status = "running"
        self.heartbeat_results: list[bool] = []
        self.heartbeats: list[tuple[str, int]] = []
        self.failure = None
        self.success = None
        self.execution_context = None
        semantic, hints = plan_to_documents(download_plan())
        self.source = SimpleNamespace(
            inspection_id=uuid4(),
            owner_hash="a" * 64,
            thumbnail_available=False,
            semantic_plan=semantic,
            provider_hints=hints,
            extractor_key="Controlled",
            provider_media_id="video-1",
            access_context={
                "provider_key": "generic",
                "profile_version": "1",
                "access_mode": "anonymous",
                "credential_version_id": None,
                "egress_affinity_id": "default",
                "client_profile_id": "yt-dlp-default",
                "attestation_provider_version": None,
                "engine_commit": "5d6b8c8",
                "runtime_revision": "a" * 64,
            },
            url_ciphertext=b"ciphertext",
            url_nonce=b"nonce",
            url_key_id="fernet",
        )

    async def claim_job(self, *args, **kwargs):
        if not self.claimed:
            return None
        return SimpleNamespace(id=self.job_id, attempt=1, status="running")

    async def get_job_source(self, *args, **kwargs):
        return self.source

    async def heartbeat(self, *args, stage: str, progress: int, **kwargs) -> bool:
        self.heartbeats.append((stage, progress))
        return self.heartbeat_results.pop(0) if self.heartbeat_results else True

    async def record_execution_context(
        self, _job_id, _worker_id, _attempt, context, _now
    ):
        self.execution_context = context

    async def get_job(self, *args, **kwargs):
        return SimpleNamespace(
            id=self.job_id,
            status=self.status,
            attempt=1,
            lease_owner="worker-1" if self.status == "running" else None,
            lease_expires_at=NOW + timedelta(minutes=1),
        )

    async def complete_success(self, *args, **kwargs):
        self.success = args[3]

    async def complete_failure(self, *args, **kwargs):
        self.failure = kwargs
        self.status = "retry_wait" if kwargs["retryable"] else "failed"
        return await self.get_job()


class FakeRunner:
    def __init__(self, artifact: RunnerArtifact) -> None:
        self.artifact = artifact
        self.error: Exception | None = None
        self.delay = 0.0
        self.status_delay = 0.0
        self.block = False
        self.cancelled = 0
        self.download_arguments = None
        self.current_context: ProviderAccessContextRef | None = None

    async def context(
        self, url: str, access_mode: ProviderAccessMode
    ) -> ProviderAccessContextRef:
        if self.current_context is not None:
            return self.current_context
        return ProviderAccessContextRef.from_document(self.source_context)

    async def download(self, task_id, url, plan, **kwargs):
        self.download_arguments = (task_id, url, plan, kwargs)
        if self.error is not None:
            raise self.error
        if self.block:
            await asyncio.Event().wait()
        if self.delay:
            await asyncio.sleep(self.delay)
        self.artifact = replace(self.artifact, task_id=task_id)
        return self.artifact

    async def status(self, task_id: str) -> RunnerProgress:
        if self.status_delay:
            await asyncio.sleep(self.status_delay)
        return RunnerProgress(DownloadStage.DOWNLOADING, 45)

    async def cancel(self, task_id: str) -> None:
        self.cancelled += 1


class FakeStorage:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, Path, str]] = []
        self.deleted: list[str] = []
        self.error: Exception | None = None

    async def upload(self, key: str, source: Path, content_type: str) -> int:
        self.uploads.append((key, source, content_type))
        if self.error is not None:
            raise self.error
        return source.stat().st_size

    async def delete(self, key: str) -> None:
        self.deleted.append(key)


class FakeCipher:
    def decrypt(self, envelope: EncryptedUrl) -> str:
        return "https://media.example/video"


class FakeCleaner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path | None]] = []

    async def cleanup(self, task_id: str, workspace: Path | None) -> None:
        self.calls.append((task_id, workspace))


class FakeThumbnailRecovery:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str, Path]] = []
        self.error: Exception | None = None

    async def recover(
        self, inspection_id: UUID, owner_hash: str, artifact: Path
    ) -> bool:
        self.calls.append((inspection_id, owner_hash, artifact))
        if self.error is not None:
            raise self.error
        return True


@dataclass
class ExecutionFixture:
    job_id: UUID
    repository: FakeRepository
    runner: FakeRunner
    storage: FakeStorage
    cleaner: FakeCleaner
    thumbnail_recovery: FakeThumbnailRecovery
    execution: DownloadExecution


def fixture(
    artifact: RunnerArtifact,
    *,
    heartbeat_interval: float = 0.001,
    recover_thumbnail: bool = False,
) -> ExecutionFixture:
    job_id = uuid4()
    repository = FakeRepository(job_id)
    runner = FakeRunner(artifact)
    runner.source_context = repository.source.access_context
    storage = FakeStorage()
    cleaner = FakeCleaner()
    thumbnail_recovery = FakeThumbnailRecovery()
    execution = DownloadExecution(
        repository=repository,
        runner=runner,
        storage=storage,
        url_cipher=FakeCipher(),
        workspace_cleaner=cleaner,
        clock=lambda: NOW,
        settings=DownloadExecutionSettings(
            worker_id="worker-1",
            bucket="video-artifacts",
            workspace_root=artifact.workspace.parent,
            lease_for=timedelta(seconds=60),
            heartbeat_interval=heartbeat_interval,
            max_file_size_bytes=1024 * 1024,
        ),
        thumbnail_recovery=thumbnail_recovery if recover_thumbnail else None,
    )
    return ExecutionFixture(
        job_id,
        repository,
        runner,
        storage,
        cleaner,
        thumbnail_recovery,
        execution,
    )


def download_plan() -> DownloadPlan:
    return DownloadPlan(
        height=720,
        width=1280,
        fps_bucket=FpsBucket.FPS_30,
        dynamic_range=DynamicRange.SDR,
        video_codec_family=VideoCodecFamily.H264,
        audio_codec_family=AudioCodecFamily.AAC,
        audio_language=None,
        container_preference=ContainerPreference.MP4,
        compatibility_profile=CompatibilityProfile.BALANCED,
        hints=ProviderHints(video_id="video-id", audio_id="audio-id"),
    )
