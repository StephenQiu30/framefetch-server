"""Strict public contracts for screenplay document imports."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt

from app.schemas.common import StrictModel
from app.schemas.media_imports import CompletedPartRequest, UploadPartResponse
from app.services.documents.models import DocumentPage, DocumentView
from app.services.imports.models import ImportView, UploadSessionView
from app.services.imports.rules.enums import ImportErrorCode, ImportStatus

type DocumentSourceFormat = Literal[
    "docx", "pdf", "txt", "markdown", "fountain", "srt", "vtt"
]


class DocumentImportRequest(StrictModel):
    file_name: str = Field(min_length=1, max_length=512)
    source_format: DocumentSourceFormat
    declared_size_bytes: StrictInt = Field(gt=0)
    declared_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rights_accepted: StrictBool


class DocumentImportResponse(StrictModel):
    id: UUID
    source_format: DocumentSourceFormat
    original_filename: str
    declared_size_bytes: int
    status: ImportStatus
    attempt: int
    error_code: ImportErrorCode | None
    version: int
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None

    @classmethod
    def from_view(cls, view: ImportView) -> DocumentImportResponse:
        return cls(
            id=view.id,
            source_format=cast(DocumentSourceFormat, view.source_format.value),
            original_filename=view.display_name,
            declared_size_bytes=view.declared_size_bytes,
            status=view.status,
            attempt=view.attempt,
            error_code=view.error_code,
            version=view.version,
            created_at=view.created_at,
            updated_at=view.updated_at,
            finished_at=view.finished_at,
        )


class DocumentUploadSessionResponse(StrictModel):
    resource_id: UUID
    attempt: int
    part_size_bytes: int
    part_count: int
    max_concurrency: int
    expires_at: datetime
    parts: tuple[UploadPartResponse, ...]

    @classmethod
    def from_view(cls, view: UploadSessionView) -> DocumentUploadSessionResponse:
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


class CompleteDocumentImportRequest(StrictModel):
    parts: tuple[CompletedPartRequest, ...] = Field(min_length=1, max_length=10_000)


class DocumentResponse(StrictModel):
    id: UUID
    title: str
    original_filename: str
    source_format: DocumentSourceFormat
    declared_size_bytes: int
    status: ImportStatus
    attempt: int
    error_code: ImportErrorCode | None
    version: int
    detected_language: str | None
    scene_count: int | None
    character_count: int | None
    quality_warnings: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None

    @classmethod
    def from_view(cls, view: DocumentView) -> DocumentResponse:
        return cls(
            id=view.id,
            title=view.title,
            original_filename=view.original_filename,
            source_format=cast(DocumentSourceFormat, view.source_format.value),
            declared_size_bytes=view.declared_size_bytes,
            status=view.status,
            attempt=view.attempt,
            error_code=view.error_code,
            version=view.version,
            detected_language=view.detected_language,
            scene_count=view.scene_count,
            character_count=view.character_count,
            quality_warnings=view.quality_warnings,
            created_at=view.created_at,
            updated_at=view.updated_at,
            finished_at=view.finished_at,
        )


class DocumentParseSummaryResponse(StrictModel):
    page_count: StrictInt | None = Field(gt=0)
    paragraph_count: StrictInt = Field(gt=0)
    heading_count: StrictInt = Field(ge=0)
    list_item_count: StrictInt = Field(ge=0)
    table_count: StrictInt = Field(ge=0)
    dialogue_block_count: StrictInt = Field(ge=0)


class DocumentDetailResponse(DocumentResponse):
    preview: str | None = Field(max_length=1_000_000)
    preview_truncated: bool
    parse_summary: DocumentParseSummaryResponse | None

    @classmethod
    def from_view(cls, view: DocumentView) -> DocumentDetailResponse:
        return cls.model_validate(
            DocumentResponse.from_view(view).model_dump()
            | {
                "preview": view.preview,
                "preview_truncated": view.preview_truncated,
                "parse_summary": (
                    None
                    if view.parse_summary is None
                    else DocumentParseSummaryResponse.model_validate(
                        {
                            "page_count": view.parse_summary.page_count,
                            "paragraph_count": view.parse_summary.paragraph_count,
                            "heading_count": view.parse_summary.heading_count,
                            "list_item_count": view.parse_summary.list_item_count,
                            "table_count": view.parse_summary.table_count,
                            "dialogue_block_count": (
                                view.parse_summary.dialogue_block_count
                            ),
                        }
                    )
                ),
            }
        )


class DocumentPageResponse(StrictModel):
    items: tuple[DocumentResponse, ...]
    page: int
    page_size: int
    total: int

    @classmethod
    def from_view(cls, view: DocumentPage) -> DocumentPageResponse:
        return cls(
            items=tuple(DocumentResponse.from_view(item) for item in view.items),
            page=view.page,
            page_size=view.page_size,
            total=view.total,
        )
