from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.services.downloads.rules.enums import (
    DownloadErrorCode,
    DownloadSourceKind,
    DownloadStage,
    DownloadStatus,
    MediaKind,
)
from app.services.downloads.rules.formats import DownloadPlan
from app.services.provider_types import ExecutionContext
from app.services.quotas import UserQuota

DEFAULT_MAX_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class DownloadCreate:
    id: UUID
    inspection_id: UUID | None
    format_id: UUID | None
    owner_hash: str
    idempotency_key: str
    request_fingerprint: str
    semantic_plan: dict[str, object]
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    source_kind: DownloadSourceKind = DownloadSourceKind.REMOTE_PROVIDER
    # A retry may outlive the short-lived inspection record. The worker still
    # re-inspects the provider source before selecting streams or writing an
    # artifact, so this only changes admission-time expiry handling.
    allow_expired_source: bool = False
    quota: UserQuota = UserQuota()


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    id: UUID
    inspection_id: UUID | None
    format_id: UUID | None
    owner_hash: str
    request_fingerprint: str
    semantic_plan: dict[str, object]
    status: str
    stage: str | None
    progress: int
    attempt: int
    max_attempts: int
    version: int
    lease_owner: str | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    started_at: datetime | None
    retry_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    source_kind: str = DownloadSourceKind.REMOTE_PROVIDER.value
    error_message: str | None = None
    execution_context: ExecutionContext | None = None

    @classmethod
    def queued(cls, command: DownloadCreate, *, now: datetime) -> JobSnapshot:
        return cls(
            id=command.id,
            inspection_id=command.inspection_id,
            format_id=command.format_id,
            owner_hash=command.owner_hash,
            request_fingerprint=command.request_fingerprint,
            semantic_plan=command.semantic_plan,
            status="queued",
            stage=None,
            progress=0,
            attempt=0,
            max_attempts=command.max_attempts,
            version=0,
            lease_owner=None,
            lease_expires_at=None,
            heartbeat_at=None,
            started_at=None,
            retry_at=None,
            finished_at=None,
            error_code=None,
            created_at=now,
            updated_at=now,
            source_kind=command.source_kind.value,
        )


@dataclass(frozen=True, slots=True)
class JobSaveResult:
    job: JobSnapshot
    created: bool


@dataclass(frozen=True, slots=True)
class ArtifactSnapshot:
    id: UUID
    job_id: UUID
    attempt: int
    bucket: str
    object_key: str
    sha256: str
    size_bytes: int
    duration_ms: int
    container: str
    content_type: str
    media_metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class DownloadPresentationSnapshot:
    title: str
    extractor_key: str
    duration_seconds: int
    thumbnail_available: bool


@dataclass(frozen=True, slots=True)
class DownloadView:
    id: UUID
    inspection_id: UUID | None
    format_id: UUID | None
    status: DownloadStatus
    stage: DownloadStage | None
    progress: int
    attempt: int
    error_code: DownloadErrorCode | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    file_available: bool = False
    version: int = 0
    title: str | None = None
    extractor_key: str | None = None
    duration_seconds: int | None = None
    thumbnail_url: str | None = None
    format_plan: DownloadPlan | None = None
    source_kind: DownloadSourceKind = DownloadSourceKind.REMOTE_PROVIDER
    source_label: str = "链接下载"
    media_kind: MediaKind = MediaKind.VIDEO
    asset_count: int = 0
    error_message: str | None = None
    execution_context: ExecutionContext | None = None


@dataclass(frozen=True, slots=True)
class DownloadUrl:
    url: str
    expires_at: datetime
    filename: str


@dataclass(frozen=True, slots=True)
class DownloadCleanupRef:
    object_key: str
    upload_id: str | None = None


@dataclass(frozen=True, slots=True)
class DownloadDeletionPlan:
    job_id: UUID
    owner_hash: str
    attempt: int
    cleanup: tuple[DownloadCleanupRef, ...] = ()
