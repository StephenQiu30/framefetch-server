from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt

from app.schemas.common import StrictModel
from app.services.imports.models import ImportView, UploadSessionView
from app.services.imports.rules.enums import (
    DeclaredOrigin,
    ImportErrorCode,
    ImportSourceFormat,
    ImportStatus,
)


class MediaImportRequest(StrictModel):
    """Untrusted browser declarations for one local MP4 resource."""

    file_name: str = Field(min_length=1, max_length=512)
    declared_size_bytes: StrictInt = Field(gt=0)
    declared_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    remove_watermark: StrictBool = False
    rights_accepted: StrictBool
    declared_origin: DeclaredOrigin = DeclaredOrigin.USER_FILE


class MediaImportResponse(StrictModel):
    """Owner-scoped public state without storage credentials or object keys."""

    id: UUID
    download_id: UUID
    source_format: ImportSourceFormat
    display_name: str
    declared_size_bytes: int
    status: ImportStatus
    attempt: int
    error_code: ImportErrorCode | None
    version: int
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    declared_origin: DeclaredOrigin

    @classmethod
    def from_view(cls, view: ImportView) -> MediaImportResponse:
        return cls(
            id=view.id,
            download_id=view.id,
            source_format=view.source_format,
            display_name=view.display_name,
            declared_size_bytes=view.declared_size_bytes,
            status=view.status,
            attempt=view.attempt,
            error_code=view.error_code,
            version=view.version,
            created_at=view.created_at,
            updated_at=view.updated_at,
            finished_at=view.finished_at,
            declared_origin=view.declared_origin,
        )


class UploadPartResponse(StrictModel):
    part_number: int
    url: str


class MediaUploadSessionResponse(StrictModel):
    resource_id: UUID
    attempt: int
    part_size_bytes: int
    part_count: int
    max_concurrency: int
    expires_at: datetime
    parts: tuple[UploadPartResponse, ...]

    @classmethod
    def from_view(cls, view: UploadSessionView) -> MediaUploadSessionResponse:
        return cls(
            resource_id=view.resource_id,
            attempt=view.attempt,
            part_size_bytes=view.part_size_bytes,
            part_count=view.part_count,
            max_concurrency=view.max_concurrency,
            expires_at=view.expires_at,
            parts=tuple(
                UploadPartResponse(part_number=part.part_number, url=part.url)
                for part in view.parts
            ),
        )


class CompletedPartRequest(StrictModel):
    part_number: StrictInt = Field(ge=1, le=10_000)
    etag: str = Field(
        min_length=32,
        max_length=34,
        pattern=r'^(?:[0-9a-fA-F]{32}|"[0-9a-fA-F]{32}")$',
    )


class CompleteMediaImportRequest(StrictModel):
    parts: tuple[CompletedPartRequest, ...] = Field(min_length=1, max_length=10_000)
