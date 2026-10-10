from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from app.services.imports.rules.enums import (
    ContentKind,
    DeclaredOrigin,
    ImportErrorCode,
    ImportSourceFormat,
    ImportStatus,
)
from app.services.quotas import UserQuota


class ImportDisposition(StrEnum):
    ACK = "ack"
    RETRY = "retry"


@dataclass(frozen=True, slots=True)
class UploadLimits:
    part_size_bytes: int
    max_parts: int
    max_concurrency: int
    session_ttl: timedelta

    def __post_init__(self) -> None:
        if (
            isinstance(self.part_size_bytes, bool)
            or not 5 * 1024**2 <= self.part_size_bytes <= 5 * 1024**3
        ):
            raise ValueError("multipart part size must be between 5 MiB and 5 GiB")
        if isinstance(self.max_parts, bool) or not 1 <= self.max_parts <= 10_000:
            raise ValueError("multipart part limit must be between 1 and 10000")
        if (
            isinstance(self.max_concurrency, bool)
            or not 1 <= self.max_concurrency <= 16
        ):
            raise ValueError("multipart concurrency must be between 1 and 16")
        if not timedelta(minutes=1) <= self.session_ttl <= timedelta(hours=1):
            raise ValueError("upload session TTL must be between 1 and 60 minutes")

    def part_count(self, size_bytes: int) -> int:
        if isinstance(size_bytes, bool) or size_bytes <= 0:
            raise ValueError("declared size must be positive")
        count = (size_bytes + self.part_size_bytes - 1) // self.part_size_bytes
        if count > self.max_parts:
            raise ValueError("declared size exceeds multipart budget")
        return count


@dataclass(frozen=True, slots=True)
class ImportResourceCreate:
    id: UUID
    owner_hash: str = field(repr=False)
    idempotency_key: str = field(repr=False)
    request_fingerprint: str = field(repr=False)
    content_kind: ContentKind
    source_format: ImportSourceFormat
    display_name: str = field(repr=False)
    content_type: str
    declared_size_bytes: int
    declared_sha256: str = field(repr=False)
    rights_statement_version: str
    declared_origin: DeclaredOrigin = DeclaredOrigin.USER_FILE
    remove_watermark: bool = False
    quota: UserQuota = UserQuota()


@dataclass(frozen=True, slots=True)
class ImportAttemptSnapshot:
    resource_id: UUID
    content_kind: str
    attempt: int
    status: str
    object_key: str = field(repr=False)
    upload_id: str | None = field(repr=False)
    content_type: str
    declared_size_bytes: int
    part_size_bytes: int
    part_count: int
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ImportCleanupRef:
    object_key: str = field(repr=False)
    upload_id: str | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class BeginUploadAttemptResult:
    attempt: ImportAttemptSnapshot
    superseded: tuple[ImportCleanupRef, ...] = ()


@dataclass(frozen=True, slots=True)
class ImportResourceSnapshot:
    id: UUID
    owner_hash: str = field(repr=False)
    content_kind: str
    source_format: str
    display_name: str = field(repr=False)
    declared_size_bytes: int
    declared_sha256: str = field(repr=False)
    status: str
    attempt: int
    error_code: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    declared_origin: str = DeclaredOrigin.USER_FILE.value
    active_attempt: ImportAttemptSnapshot | None = None


@dataclass(frozen=True, slots=True)
class ImportResourceSaveResult:
    resource: ImportResourceSnapshot
    created: bool


@dataclass(frozen=True, slots=True)
class CancelImportResult:
    resource: ImportResourceSnapshot
    cleanup: tuple[ImportCleanupRef, ...] = ()


@dataclass(frozen=True, slots=True)
class CompletedUploadPart:
    part_number: int
    etag: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class UploadPartTarget:
    part_number: int
    url: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class UploadSessionView:
    resource_id: UUID
    attempt: int
    part_size_bytes: int
    part_count: int
    max_concurrency: int
    expires_at: datetime
    parts: tuple[UploadPartTarget, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class ImportView:
    id: UUID
    content_kind: ContentKind
    source_format: ImportSourceFormat
    display_name: str = field(repr=False)
    declared_size_bytes: int
    status: ImportStatus
    attempt: int
    error_code: ImportErrorCode | None
    version: int
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    declared_origin: DeclaredOrigin = DeclaredOrigin.USER_FILE
