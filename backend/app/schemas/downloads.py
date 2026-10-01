from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.common import StrictModel
from app.schemas.inspections import SemanticPlanResponse
from app.services.downloads.download_models import DownloadUrl, DownloadView
from app.services.downloads.rules.enums import (
    DownloadErrorCode,
    DownloadSourceKind,
    DownloadStage,
    DownloadStatus,
    MediaKind,
)
from app.services.provider_types import ExecutionContext


class DownloadRequest(StrictModel):
    """References an inspection and one format returned by that inspection."""

    inspection_id: UUID = Field(description="仍在有效期内的媒体解析资源 ID。")
    format_id: UUID = Field(description="解析结果中选择的语义下载格式 ID。")


class DownloadResponse(StrictModel):
    """Current state of a durable asynchronous download resource."""

    execution_context: ExecutionContext | None = Field(
        default=None,
        json_schema_extra={"readOnly": True},
        description="实际执行的十二字段非敏感上下文；本地导入无解析上下文。",
    )

    id: UUID
    inspection_id: UUID | None
    format_id: UUID | None
    source_kind: DownloadSourceKind
    source_label: str
    status: DownloadStatus
    stage: DownloadStage | None
    progress: int
    attempt: int
    version: int
    error_code: DownloadErrorCode | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    file_available: bool
    title: str | None
    extractor_key: str | None
    duration_seconds: int | None
    media_kind: MediaKind
    asset_count: int
    thumbnail_url: str | None
    format: SemanticPlanResponse | None

    @classmethod
    def from_view(cls, view: DownloadView) -> DownloadResponse:
        format_plan = view.format_plan
        return cls(
            execution_context=view.execution_context,
            id=view.id,
            inspection_id=view.inspection_id,
            format_id=view.format_id,
            source_kind=view.source_kind,
            source_label=view.source_label,
            status=view.status,
            stage=view.stage,
            progress=view.progress,
            attempt=view.attempt,
            version=view.version,
            error_code=view.error_code,
            error_message=view.error_message,
            created_at=view.created_at,
            updated_at=view.updated_at,
            finished_at=view.finished_at,
            file_available=view.file_available,
            title=view.title,
            extractor_key=view.extractor_key,
            duration_seconds=view.duration_seconds,
            media_kind=view.media_kind,
            asset_count=view.asset_count,
            thumbnail_url=view.thumbnail_url,
            format=(
                None
                if format_plan is None
                else SemanticPlanResponse(
                    height=format_plan.height,
                    width=format_plan.width,
                    fps_bucket=format_plan.fps_bucket,
                    dynamic_range=format_plan.dynamic_range,
                    video_codec_family=format_plan.video_codec_family,
                    audio_codec_family=format_plan.audio_codec_family,
                    audio_language=format_plan.audio_language,
                    container_preference=format_plan.container_preference,
                    compatibility_profile=format_plan.compatibility_profile,
                )
            ),
        )


class DownloadUrlResponse(StrictModel):
    """Short-lived URL for retrieving a completed download artifact."""

    url: str
    expires_at: datetime
    filename: str

    @classmethod
    def from_view(cls, view: DownloadUrl) -> DownloadUrlResponse:
        return cls(url=view.url, expires_at=view.expires_at, filename=view.filename)
