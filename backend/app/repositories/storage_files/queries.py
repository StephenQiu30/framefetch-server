from __future__ import annotations

from typing import Any

from sqlalchemy import Text, cast, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import as_utc
from app.models import (
    AnalysisJobRow,
    AnalysisReportArtifactRow,
    AnalysisReportVersionRow,
    ArtifactRow,
    DocumentArtifactRow,
    DocumentRow,
    DownloadJobRow,
    MediaImportRow,
    MediaInspectionRow,
    UserRow,
)
from app.services.analysis.rules.enums import (
    AnalysisReportArtifactStatus,
    AnalysisReportStatus,
)
from app.services.storage_files.models import StoredFilePage, StoredFileView


async def list_stored_files(
    sessions: async_sessionmaker[AsyncSession], *, page: int, page_size: int
) -> StoredFilePage:
    files = _stored_files_statement().subquery()
    async with sessions() as session:
        total = await session.scalar(select(func.count()).select_from(files))
        rows = (
            await session.execute(
                select(files, UserRow.username.label("uploader_username"))
                .outerjoin(
                    UserRow,
                    files.c.owner_hash
                    == func.encode(
                        func.sha256(func.convert_to(cast(UserRow.id, Text), "UTF8")),
                        "hex",
                    ),
                )
                .order_by(files.c.created_at.desc(), files.c.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).mappings()
        return StoredFilePage(
            items=tuple(
                StoredFileView(
                    id=row["id"],
                    category=row["category"],
                    name=row["name"],
                    uploader_username=row["uploader_username"],
                    object_count=int(row["object_count"]),
                    size_bytes=int(row["size_bytes"]),
                    created_at=as_utc(row["created_at"]),
                )
                for row in rows
            ),
            page=page,
            page_size=page_size,
            total=int(total or 0),
        )


def _stored_files_statement() -> Any:
    from app.models.watermark import WatermarkTaskRow

    derivatives = (
        select(
            WatermarkTaskRow.source_id.label("source_id"),
            func.sum(WatermarkTaskRow.size_bytes).label("bytes"),
            func.count().label("count"),
        )
        .where(WatermarkTaskRow.size_bytes > 0)
        .group_by(WatermarkTaskRow.source_id)
        .subquery()
    )
    video_name = func.coalesce(
        MediaImportRow.display_name,
        MediaInspectionRow.title,
        literal("视频文件"),
    )
    videos = (
        select(
            ArtifactRow.id.label("id"),
            literal("video").label("category"),
            video_name.label("name"),
            DownloadJobRow.owner_hash.label("owner_hash"),
            (1 + func.coalesce(derivatives.c.count, 0)).label("object_count"),
            (ArtifactRow.size_bytes + func.coalesce(derivatives.c.bytes, 0)).label(
                "size_bytes"
            ),
            ArtifactRow.created_at.label("created_at"),
        )
        .outerjoin(derivatives, derivatives.c.source_id == ArtifactRow.id)
        .join(DownloadJobRow, DownloadJobRow.id == ArtifactRow.job_id)
        .outerjoin(
            MediaInspectionRow,
            MediaInspectionRow.id == DownloadJobRow.inspection_id,
        )
        .outerjoin(MediaImportRow, MediaImportRow.id == DownloadJobRow.id)
        .where(ArtifactRow.deleted_at.is_(None))
    )
    documents = (
        select(
            DocumentRow.id.label("id"),
            literal("screenplay").label("category"),
            DocumentRow.title.label("name"),
            DocumentRow.owner_hash.label("owner_hash"),
            func.count(DocumentArtifactRow.id).label("object_count"),
            func.sum(DocumentArtifactRow.size_bytes).label("size_bytes"),
            DocumentRow.created_at.label("created_at"),
        )
        .join(DocumentArtifactRow, DocumentArtifactRow.document_id == DocumentRow.id)
        .where(
            DocumentRow.deleted_at.is_(None),
            DocumentRow.status == "ready",
            DocumentArtifactRow.status == "ready",
            DocumentArtifactRow.deleted_at.is_(None),
        )
        .group_by(
            DocumentRow.id,
            DocumentRow.title,
            DocumentRow.owner_hash,
            DocumentRow.created_at,
        )
    )
    reports = (
        select(
            AnalysisReportVersionRow.id.label("id"),
            literal("analysis_report").label("category"),
            literal("分析报告").label("name"),
            AnalysisJobRow.owner_hash.label("owner_hash"),
            func.count(AnalysisReportArtifactRow.id).label("object_count"),
            func.sum(AnalysisReportArtifactRow.size_bytes).label("size_bytes"),
            AnalysisReportVersionRow.created_at.label("created_at"),
        )
        .join(
            AnalysisReportArtifactRow,
            AnalysisReportArtifactRow.report_id == AnalysisReportVersionRow.id,
        )
        .join(AnalysisJobRow, AnalysisJobRow.id == AnalysisReportVersionRow.job_id)
        .where(
            AnalysisReportVersionRow.status == AnalysisReportStatus.AVAILABLE.value,
            AnalysisReportArtifactRow.status
            == AnalysisReportArtifactStatus.AVAILABLE.value,
            AnalysisReportArtifactRow.deleted_at.is_(None),
        )
        .group_by(
            AnalysisReportVersionRow.id,
            AnalysisReportVersionRow.created_at,
            AnalysisJobRow.owner_hash,
        )
    )
    return union_all(videos, documents, reports)
