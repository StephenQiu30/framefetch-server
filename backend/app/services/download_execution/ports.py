from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol
from uuid import UUID

from app.services.download_execution.models import ArtifactDetails
from app.services.downloads.inspection_models import EncryptedUrl
from app.services.downloads.rules.enums import DownloadStage, MediaKind
from app.services.downloads.rules.formats import DownloadPlan
from app.services.provider_types import ExecutionContext


class JobState(Protocol):
    @property
    def status(self) -> str: ...

    @property
    def attempt(self) -> int: ...

    @property
    def lease_owner(self) -> str | None: ...

    @property
    def lease_expires_at(self) -> datetime | None: ...


class JobSource(Protocol):
    @property
    def inspection_id(self) -> UUID: ...

    @property
    def owner_hash(self) -> str: ...

    @property
    def thumbnail_available(self) -> bool: ...

    @property
    def semantic_plan(self) -> dict[str, object]: ...

    @property
    def provider_hints(self) -> dict[str, object]: ...

    @property
    def extractor_key(self) -> str: ...

    @property
    def provider_media_id(self) -> str: ...

    @property
    def execution_context(self) -> dict[str, object]: ...

    @property
    def url_ciphertext(self) -> bytes: ...

    @property
    def url_nonce(self) -> bytes: ...

    @property
    def url_key_id(self) -> str: ...


class RunnerArtifactView(Protocol):
    @property
    def task_id(self) -> str: ...

    @property
    def workspace(self) -> Path: ...

    @property
    def artifact(self) -> Path: ...

    @property
    def size_bytes(self) -> int: ...

    @property
    def sha256(self) -> str: ...

    @property
    def duration_seconds(self) -> float: ...

    @property
    def container(self) -> str: ...

    @property
    def video_streams(self) -> int: ...

    @property
    def audio_streams(self) -> int: ...

    @property
    def media_kind(self) -> MediaKind: ...

    @property
    def asset_count(self) -> int: ...


class RunnerProgressView(Protocol):
    @property
    def stage(self) -> DownloadStage: ...

    @property
    def progress(self) -> int: ...


class ExecutionRepository(Protocol):
    async def claim_job(
        self, job_id: UUID, worker_id: str, now: datetime, lease_for: timedelta
    ) -> JobState | None: ...

    async def get_job(self, job_id: UUID) -> JobState: ...

    async def get_job_source(
        self, job_id: UUID, worker_id: str, attempt: int, now: datetime
    ) -> JobSource: ...

    async def heartbeat(
        self,
        job_id: UUID,
        worker_id: str,
        attempt: int,
        *,
        stage: str,
        stage_rank: int,
        progress: int,
        now: datetime,
        lease_for: timedelta,
    ) -> bool: ...

    async def record_execution_context(
        self,
        job_id: UUID,
        worker_id: str,
        attempt: int,
        context: ExecutionContext,
        now: datetime,
    ) -> None: ...

    async def complete_success(
        self,
        job_id: UUID,
        worker_id: str,
        attempt: int,
        artifact: ArtifactDetails,
        *,
        now: datetime,
    ) -> None: ...

    async def complete_failure(
        self,
        job_id: UUID,
        worker_id: str,
        attempt: int,
        *,
        error_code: str,
        error_message: str,
        retryable: bool,
        now: datetime,
        retry_at: datetime | None,
    ) -> JobState: ...


class ExecutionRunner(Protocol):
    async def download(
        self,
        task_id: str,
        url: str,
        plan: DownloadPlan | None,
        *,
        expected_provider_media_id: str,
        expected_extractor_key: str,
        execution_context: ExecutionContext,
        media_kind: MediaKind = MediaKind.VIDEO,
        asset_count: int = 0,
    ) -> RunnerArtifactView: ...

    async def status(self, task_id: str) -> RunnerProgressView: ...

    async def cancel(self, task_id: str) -> None: ...


class ExecutionStorage(Protocol):
    async def upload(self, object_key: str, source: Path, content_type: str) -> int: ...

    async def delete(self, object_key: str) -> None: ...


class UrlDecryptor(Protocol):
    def decrypt(self, envelope: EncryptedUrl) -> str: ...


class WorkspaceCleaner(Protocol):
    async def cleanup(self, task_id: str, workspace: Path | None) -> None: ...


class ThumbnailRecovery(Protocol):
    async def recover(
        self,
        inspection_id: UUID,
        owner_hash: str,
        artifact: Path,
    ) -> bool: ...


type Clock = Callable[[], datetime]
