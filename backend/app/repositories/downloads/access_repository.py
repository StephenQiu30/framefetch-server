"""Owner-scoped cancellation and artifact lookup operations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select

from app.core.db import as_utc, utc_now
from app.models import (
    ArtifactRow,
    DownloadJobRow,
    DownloadThumbnailRow,
    MediaFormatRow,
    MediaImportRow,
    MediaInspectionRow,
    MediaThumbnailRow,
)
from app.repositories.contracts import (
    DownloadThumbnailCandidateSnapshot,
    JobSourceSnapshot,
)
from app.repositories.downloads.mapping import (
    artifact_snapshot,
    download_history_item_snapshot,
    download_history_page_snapshot,
    job_snapshot,
)
from app.repositories.errors import (
    LeaseConflict,
    RepositoryConflict,
    RepositoryNotFound,
)
from app.repositories.repository_base import RepositoryBase
from app.services.downloads.download_models import (
    ArtifactSnapshot,
    DownloadPresentationSnapshot,
    JobSnapshot,
)
from app.services.downloads.history_models import DownloadHistoryPageSnapshot
from app.services.downloads.thumbnail import (
    DownloadThumbnailSource,
    ThumbnailObject,
    ThumbnailSource,
)


class AccessRepository(RepositoryBase):
    async def list_missing_download_thumbnails(
        self, *, limit: int
    ) -> tuple[DownloadThumbnailCandidateSnapshot, ...]:
        if not 1 <= limit <= 200:
            raise ValueError("thumbnail backfill limit is invalid")
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(DownloadJobRow, ArtifactRow)
                    .join(ArtifactRow, ArtifactRow.job_id == DownloadJobRow.id)
                    .outerjoin(
                        DownloadThumbnailRow,
                        DownloadThumbnailRow.job_id == DownloadJobRow.id,
                    )
                    .where(
                        DownloadJobRow.source_kind == "browser_import",
                        DownloadJobRow.status == "succeeded",
                        ArtifactRow.deleted_at.is_(None),
                        DownloadThumbnailRow.job_id.is_(None),
                    )
                    .order_by(DownloadJobRow.created_at, DownloadJobRow.id)
                    .limit(limit)
                )
            ).all()
        return tuple(
            DownloadThumbnailCandidateSnapshot(
                job_id=job.id,
                owner_hash=job.owner_hash,
                object_key=artifact.object_key,
            )
            for job, artifact in rows
        )

    async def get_download_presentation(
        self, job_id: UUID, owner_hash: str
    ) -> DownloadPresentationSnapshot:
        async with self._sessions() as session:
            result = (
                await session.execute(
                    select(MediaInspectionRow, MediaThumbnailRow)
                    .join(
                        DownloadJobRow,
                        DownloadJobRow.inspection_id == MediaInspectionRow.id,
                    )
                    .outerjoin(
                        MediaThumbnailRow,
                        MediaThumbnailRow.inspection_id == MediaInspectionRow.id,
                    )
                    .where(
                        DownloadJobRow.id == job_id,
                        DownloadJobRow.owner_hash == owner_hash,
                        MediaInspectionRow.owner_hash == owner_hash,
                    )
                )
            ).one_or_none()
            if result is None:
                raise RepositoryNotFound("download presentation does not exist")
            row, stored_thumbnail = result
            metadata = dict(row.metadata_json)
            legacy_thumbnail = metadata.get("thumbnail_url")
            return DownloadPresentationSnapshot(
                title=row.title,
                extractor_key=row.extractor_key,
                duration_seconds=row.duration_seconds,
                thumbnail_available=(
                    stored_thumbnail is not None or isinstance(legacy_thumbnail, str)
                ),
            )

    async def get_thumbnail_source(
        self, inspection_id: UUID, owner_hash: str
    ) -> ThumbnailSource:
        async with self._sessions() as session:
            result = (
                await session.execute(
                    select(MediaInspectionRow, MediaThumbnailRow)
                    .outerjoin(
                        MediaThumbnailRow,
                        MediaThumbnailRow.inspection_id == MediaInspectionRow.id,
                    )
                    .where(
                        MediaInspectionRow.id == inspection_id,
                        MediaInspectionRow.owner_hash == owner_hash,
                    )
                )
            ).one_or_none()
            if result is None:
                raise RepositoryNotFound("media thumbnail does not exist")
            inspection, thumbnail = result
            legacy = inspection.metadata_json.get("thumbnail_url")
            return ThumbnailSource(
                inspection_id=inspection.id,
                owner_hash=inspection.owner_hash,
                object=(
                    None
                    if thumbnail is None
                    else ThumbnailObject(
                        bucket=thumbnail.bucket,
                        object_key=thumbnail.object_key,
                        content_type=thumbnail.content_type,
                        sha256=thumbnail.sha256,
                        size_bytes=thumbnail.size_bytes,
                    )
                ),
                legacy_data_url=legacy if isinstance(legacy, str) else None,
            )

    async def save_thumbnail(
        self,
        inspection_id: UUID,
        owner_hash: str,
        thumbnail: ThumbnailObject,
    ) -> None:
        async with self._sessions() as session, session.begin():
            inspection = await session.scalar(
                select(MediaInspectionRow)
                .where(
                    MediaInspectionRow.id == inspection_id,
                    MediaInspectionRow.owner_hash == owner_hash,
                )
                .with_for_update()
            )
            if inspection is None:
                raise RepositoryNotFound("media inspection does not exist")
            row = await session.get(MediaThumbnailRow, inspection_id)
            if row is None:
                row = MediaThumbnailRow(inspection_id=inspection_id)
                session.add(row)
            row.bucket = thumbnail.bucket
            row.object_key = thumbnail.object_key
            row.content_type = thumbnail.content_type
            row.sha256 = thumbnail.sha256
            row.size_bytes = thumbnail.size_bytes
            row.updated_at = utc_now()
            metadata = dict(inspection.metadata_json)
            metadata.pop("thumbnail_url", None)
            inspection.metadata_json = metadata
            await session.flush()

    async def get_download_thumbnail_source(
        self, job_id: UUID, owner_hash: str
    ) -> DownloadThumbnailSource:
        async with self._sessions() as session:
            result = (
                await session.execute(
                    select(DownloadJobRow, DownloadThumbnailRow)
                    .outerjoin(
                        DownloadThumbnailRow,
                        DownloadThumbnailRow.job_id == DownloadJobRow.id,
                    )
                    .where(
                        DownloadJobRow.id == job_id,
                        DownloadJobRow.owner_hash == owner_hash,
                    )
                )
            ).one_or_none()
            if result is None:
                raise RepositoryNotFound("download thumbnail does not exist")
            job, thumbnail = result
            return DownloadThumbnailSource(
                job_id=job.id,
                owner_hash=job.owner_hash,
                object=(
                    None
                    if thumbnail is None
                    else ThumbnailObject(
                        bucket=thumbnail.bucket,
                        object_key=thumbnail.object_key,
                        content_type=thumbnail.content_type,
                        sha256=thumbnail.sha256,
                        size_bytes=thumbnail.size_bytes,
                    )
                ),
            )

    async def save_download_thumbnail(
        self,
        job_id: UUID,
        owner_hash: str,
        thumbnail: ThumbnailObject,
    ) -> None:
        async with self._sessions() as session, session.begin():
            job = await session.scalar(
                select(DownloadJobRow)
                .where(
                    DownloadJobRow.id == job_id,
                    DownloadJobRow.owner_hash == owner_hash,
                )
                .with_for_update()
            )
            if job is None:
                raise RepositoryNotFound("download job does not exist")
            row = await session.get(DownloadThumbnailRow, job_id)
            if row is None:
                row = DownloadThumbnailRow(job_id=job_id)
                session.add(row)
            row.bucket = thumbnail.bucket
            row.object_key = thumbnail.object_key
            row.content_type = thumbnail.content_type
            row.sha256 = thumbnail.sha256
            row.size_bytes = thumbnail.size_bytes
            row.updated_at = utc_now()
            await session.flush()

    async def list_download_history(
        self,
        owner_hash: str,
        *,
        page: int,
        page_size: int,
        status: str | None,
        search: str | None,
        now: datetime,
    ) -> DownloadHistoryPageSnapshot:
        filters = [DownloadJobRow.owner_hash == owner_hash]
        if status is not None:
            filters.append(DownloadJobRow.status == status)
        if search:
            pattern = f"%{_escape_like(search)}%"
            filters.append(
                or_(
                    MediaInspectionRow.title.ilike(pattern, escape="\\"),
                    MediaImportRow.display_name.ilike(pattern, escape="\\"),
                )
            )
        summary_filters = [DownloadJobRow.owner_hash == owner_hash]
        if search:
            summary_filters.append(
                or_(
                    MediaInspectionRow.title.ilike(pattern, escape="\\"),
                    MediaImportRow.display_name.ilike(pattern, escape="\\"),
                )
            )
        offset = (page - 1) * page_size
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(
                        DownloadJobRow,
                        MediaInspectionRow,
                        MediaFormatRow,
                        MediaImportRow,
                        ArtifactRow,
                        MediaThumbnailRow,
                        DownloadThumbnailRow,
                    )
                    .outerjoin(
                        MediaInspectionRow,
                        MediaInspectionRow.id == DownloadJobRow.inspection_id,
                    )
                    .outerjoin(
                        MediaFormatRow, MediaFormatRow.id == DownloadJobRow.format_id
                    )
                    .outerjoin(MediaImportRow, MediaImportRow.id == DownloadJobRow.id)
                    .outerjoin(ArtifactRow, ArtifactRow.job_id == DownloadJobRow.id)
                    .outerjoin(
                        MediaThumbnailRow,
                        MediaThumbnailRow.inspection_id == MediaInspectionRow.id,
                    )
                    .outerjoin(
                        DownloadThumbnailRow,
                        DownloadThumbnailRow.job_id == DownloadJobRow.id,
                    )
                    .where(*filters)
                    .order_by(
                        DownloadJobRow.created_at.desc(), DownloadJobRow.id.desc()
                    )
                    .offset(offset)
                    .limit(page_size)
                )
            ).all()
            total = int(
                await session.scalar(
                    select(func.count(DownloadJobRow.id))
                    .outerjoin(
                        MediaInspectionRow,
                        MediaInspectionRow.id == DownloadJobRow.inspection_id,
                    )
                    .outerjoin(MediaImportRow, MediaImportRow.id == DownloadJobRow.id)
                    .where(*filters)
                )
                or 0
            )
            count_rows = (
                await session.execute(
                    select(DownloadJobRow.status, func.count(DownloadJobRow.id))
                    .outerjoin(
                        MediaInspectionRow,
                        MediaInspectionRow.id == DownloadJobRow.inspection_id,
                    )
                    .outerjoin(MediaImportRow, MediaImportRow.id == DownloadJobRow.id)
                    .where(*summary_filters)
                    .group_by(DownloadJobRow.status)
                )
            ).all()
            counts: dict[str, int] = {
                status_value: int(count) for status_value, count in count_rows
            }
        items = tuple(
            download_history_item_snapshot(
                job,
                inspection,
                selected_format,
                media_import,
                artifact,
                thumbnail,
                job_thumbnail,
                now,
            )
            for (
                job,
                inspection,
                selected_format,
                media_import,
                artifact,
                thumbnail,
                job_thumbnail,
            ) in rows
        )
        return download_history_page_snapshot(
            items, page=page, page_size=page_size, total=total, counts=counts
        )

    async def get_job_source(
        self,
        job_id: UUID,
        worker_id: str,
        attempt: int,
        now: datetime,
    ) -> JobSourceSnapshot:
        async with self._sessions() as session:
            result = (
                await session.execute(
                    select(DownloadJobRow, MediaInspectionRow, MediaFormatRow)
                    .join(
                        MediaInspectionRow,
                        MediaInspectionRow.id == DownloadJobRow.inspection_id,
                    )
                    .join(MediaFormatRow, MediaFormatRow.id == DownloadJobRow.format_id)
                    .where(DownloadJobRow.id == job_id)
                )
            ).one_or_none()
            if result is None:
                raise RepositoryNotFound("download source does not exist")
            job, inspection, selected_format = result
            if (
                job.status != "running"
                or job.lease_owner != worker_id
                or job.attempt != attempt
                or job.lease_expires_at is None
                or as_utc(job.lease_expires_at) <= as_utc(now)
            ):
                raise LeaseConflict("worker no longer owns this job attempt")
            # Inspection TTL controls new admissions. A queued retry may be
            # older than that TTL, but the Worker re-inspects before download.
            execution_context = inspection.metadata_json.get("execution_context")
            if not isinstance(execution_context, dict):
                raise RepositoryNotFound("provider access context is unavailable")
            thumbnail = await session.get(MediaThumbnailRow, inspection.id)
            return JobSourceSnapshot(
                job_id=job.id,
                inspection_id=inspection.id,
                owner_hash=job.owner_hash,
                thumbnail_available=(
                    thumbnail is not None
                    or isinstance(inspection.metadata_json.get("thumbnail_url"), str)
                ),
                semantic_plan=dict(job.semantic_plan),
                provider_hints=dict(selected_format.provider_hints),
                extractor_key=inspection.extractor_key,
                provider_media_id=inspection.provider_media_id,
                duration_seconds=inspection.duration_seconds,
                execution_context=dict(execution_context),
                url_ciphertext=inspection.url_ciphertext,
                url_nonce=inspection.url_nonce,
                url_key_id=inspection.url_key_id,
                expires_at=as_utc(inspection.expires_at),
            )

    async def cancel_job(
        self, job_id: UUID, owner_hash: str, now: datetime
    ) -> JobSnapshot:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(DownloadJobRow)
                .where(
                    DownloadJobRow.id == job_id,
                    DownloadJobRow.owner_hash == owner_hash,
                )
                .with_for_update()
            )
            if row is None:
                raise RepositoryNotFound("download job does not exist")
            cancel_job_row(row, now)
            await session.flush()
            return job_snapshot(row)

    async def get_artifact(
        self, job_id: UUID, owner_hash: str, now: datetime
    ) -> ArtifactSnapshot:
        async with self._sessions() as session:
            row = await session.scalar(
                select(ArtifactRow)
                .join(DownloadJobRow, DownloadJobRow.id == ArtifactRow.job_id)
                .where(
                    ArtifactRow.job_id == job_id,
                    ArtifactRow.deleted_at.is_(None),
                    DownloadJobRow.owner_hash == owner_hash,
                    DownloadJobRow.status == "succeeded",
                )
            )
            if row is None:
                raise RepositoryNotFound("artifact does not exist")
            return artifact_snapshot(row)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def cancel_job_row(row: DownloadJobRow, now: datetime) -> None:
    """Apply cancellation inside the caller-owned transaction and row lock."""
    if row.status == "cancelled":
        return
    if row.status not in {"queued", "running", "retry_wait"}:
        raise RepositoryConflict("terminal download job cannot be cancelled")
    row.status = "cancelled"
    row.stage = None
    row.stage_rank = 0
    row.version += 1
    row.cancel_requested_at = now
    row.finished_at = now
    row.retry_at = None
    row.error_code = "cancelled"
    row.error_message = None
    row.lease_owner = None
    row.lease_expires_at = None
    row.updated_at = now
