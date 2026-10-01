"""Convert mutable ORM rows into immutable persistence snapshots."""

from datetime import datetime

from app.core.db import as_utc
from app.models import (
    ArtifactRow,
    DownloadJobRow,
    DownloadThumbnailRow,
    MediaFormatRow,
    MediaImportRow,
    MediaInspectionRow,
    MediaThumbnailRow,
    OutboxEventRow,
)
from app.repositories.contracts import OutboxSnapshot
from app.services.downloads.download_models import ArtifactSnapshot, JobSnapshot
from app.services.downloads.history_models import (
    DownloadHistoryItemSnapshot,
    DownloadHistoryPageSnapshot,
    DownloadHistorySummarySnapshot,
)
from app.services.downloads.inspection_models import FormatSnapshot, InspectionSnapshot
from app.services.provider_types import ExecutionContext


def inspection_snapshot(
    row: MediaInspectionRow,
    formats: tuple[MediaFormatRow, ...],
    *,
    thumbnail_available: bool = False,
) -> InspectionSnapshot:
    return InspectionSnapshot(
        id=row.id,
        owner_hash=row.owner_hash,
        request_fingerprint=row.request_fingerprint,
        extractor_key=row.extractor_key,
        provider_media_id=row.provider_media_id,
        title=row.title,
        duration_seconds=row.duration_seconds,
        metadata=dict(row.metadata_json),
        thumbnail_available=thumbnail_available,
        expires_at=as_utc(row.expires_at),
        formats=tuple(
            FormatSnapshot(
                id=item.id,
                display_name=item.display_name,
                plan_fingerprint=item.plan_fingerprint,
                semantic_plan=dict(item.semantic_plan),
                provider_hints=dict(item.provider_hints),
                expires_at=as_utc(item.expires_at),
            )
            for item in formats
        ),
    )


def job_snapshot(row: DownloadJobRow) -> JobSnapshot:
    return JobSnapshot(
        execution_context=None
        if row.execution_context is None
        else ExecutionContext.from_document(row.execution_context),
        id=row.id,
        inspection_id=row.inspection_id,
        format_id=row.format_id,
        owner_hash=row.owner_hash,
        request_fingerprint=row.request_fingerprint,
        semantic_plan=dict(row.semantic_plan),
        status=row.status,
        stage=row.stage,
        progress=row.progress,
        attempt=row.attempt,
        max_attempts=row.max_attempts,
        version=row.version,
        lease_owner=row.lease_owner,
        lease_expires_at=None
        if row.lease_expires_at is None
        else as_utc(row.lease_expires_at),
        heartbeat_at=None if row.heartbeat_at is None else as_utc(row.heartbeat_at),
        started_at=None if row.started_at is None else as_utc(row.started_at),
        retry_at=None if row.retry_at is None else as_utc(row.retry_at),
        finished_at=None if row.finished_at is None else as_utc(row.finished_at),
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
        source_kind=row.source_kind,
    )


def download_history_item_snapshot(
    job: DownloadJobRow,
    inspection: MediaInspectionRow | None,
    selected_format: MediaFormatRow | None,
    media_import: MediaImportRow | None,
    artifact: ArtifactRow | None,
    thumbnail: MediaThumbnailRow | None,
    job_thumbnail: DownloadThumbnailRow | None,
    now: datetime,
) -> DownloadHistoryItemSnapshot:
    metadata = {} if inspection is None else dict(inspection.metadata_json)
    legacy_thumbnail = metadata.get("thumbnail_url")
    is_browser_import = job.source_kind == "browser_import"
    return DownloadHistoryItemSnapshot(
        id=job.id,
        inspection_id=None if inspection is None else inspection.id,
        title=(
            (media_import.display_name if media_import is not None else "本地视频")
            if is_browser_import
            else (inspection.title if inspection is not None else "未命名视频")
        ),
        thumbnail_available=(
            job_thumbnail is not None
            or (
                not is_browser_import
                and (thumbnail is not None or isinstance(legacy_thumbnail, str))
            )
        ),
        job_thumbnail_available=job_thumbnail is not None,
        format_name=(
            "MP4"
            if is_browser_import
            else (
                selected_format.display_name
                if selected_format is not None
                else "未知格式"
            )
        ),
        status=job.status,
        progress=job.progress,
        error_code=job.error_code,
        created_at=as_utc(job.created_at),
        updated_at=as_utc(job.updated_at),
        finished_at=None if job.finished_at is None else as_utc(job.finished_at),
        file_available=(
            job.status == "succeeded"
            and artifact is not None
            and artifact.deleted_at is None
        ),
        source_kind=job.source_kind,
        declared_origin=(
            None if media_import is None else media_import.declared_origin
        ),
    )


def download_history_page_snapshot(
    items: tuple[DownloadHistoryItemSnapshot, ...],
    *,
    page: int,
    page_size: int,
    total: int,
    counts: dict[str, int],
) -> DownloadHistoryPageSnapshot:
    return DownloadHistoryPageSnapshot(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        summary=DownloadHistorySummarySnapshot(
            total=sum(counts.values()),
            succeeded=counts.get("succeeded", 0),
            active=sum(
                counts.get(value, 0) for value in ("queued", "running", "retry_wait")
            ),
            failed=counts.get("failed", 0),
        ),
    )


def artifact_snapshot(row: ArtifactRow) -> ArtifactSnapshot:
    return ArtifactSnapshot(
        id=row.id,
        job_id=row.job_id,
        attempt=row.attempt,
        bucket=row.bucket,
        object_key=row.object_key,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        duration_ms=row.duration_ms,
        container=row.container,
        content_type=row.content_type,
        media_metadata=dict(row.media_metadata),
    )


def outbox_snapshot(row: OutboxEventRow) -> OutboxSnapshot:
    return OutboxSnapshot(
        id=row.id,
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        event_type=row.event_type,
        payload=dict(row.payload),
        publish_attempts=row.publish_attempts,
        available_at=as_utc(row.available_at),
        created_at=as_utc(row.created_at),
    )
