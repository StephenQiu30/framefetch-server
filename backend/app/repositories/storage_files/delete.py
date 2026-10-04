from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import (
    AnalysisArtifactLockRow,
    AnalysisDocumentLockRow,
    AnalysisReportArtifactRow,
    AnalysisReportVersionRow,
    ArtifactRow,
    CreationMaterialRow,
    DocumentArtifactRow,
    DocumentRow,
    DownloadJobRow,
)
from app.services.analysis.rules.enums import (
    AnalysisReportArtifactStatus,
    AnalysisReportStatus,
)
from app.services.storage_files.errors import StorageFileError, StorageFileErrorCode
from app.services.storage_files.models import StoredFileCategory
from app.services.storage_files.ports import DeleteStoredObject


async def delete_stored_file(
    sessions: async_sessionmaker[AsyncSession],
    *,
    category: StoredFileCategory,
    file_id: UUID,
    now: datetime,
    delete: DeleteStoredObject,
) -> None:
    if category == "video":
        await _delete_video(sessions, file_id, now, delete)
    elif category == "screenplay":
        await _delete_document(sessions, file_id, now, delete)
    else:
        await _delete_report(sessions, file_id, now, delete)


async def _delete_video(
    sessions: async_sessionmaker[AsyncSession],
    file_id: UUID,
    now: datetime,
    delete: DeleteStoredObject,
) -> None:
    async with sessions() as session, session.begin():
        artifact = await session.scalar(
            select(ArtifactRow)
            .where(ArtifactRow.id == file_id, ArtifactRow.deleted_at.is_(None))
            .with_for_update()
        )
        if artifact is None:
            raise StorageFileError(StorageFileErrorCode.NOT_FOUND)
        if (
            await session.scalar(
                select(AnalysisArtifactLockRow.job_id).where(
                    AnalysisArtifactLockRow.artifact_id == artifact.id
                )
            )
            is not None
        ):
            raise StorageFileError(StorageFileErrorCode.IN_USE)
        if (
            await session.scalar(
                select(CreationMaterialRow.id)
                .join(
                    DownloadJobRow,
                    DownloadJobRow.owner_hash == CreationMaterialRow.owner_hash,
                )
                .where(
                    CreationMaterialRow.artifact_id == artifact.id,
                    DownloadJobRow.id == artifact.job_id,
                )
                .limit(1)
            )
            is not None
        ):
            raise StorageFileError(StorageFileErrorCode.IN_USE)
        await _delete_object(delete, artifact.object_key)
        artifact.deleted_at = now


async def _delete_document(
    sessions: async_sessionmaker[AsyncSession],
    file_id: UUID,
    now: datetime,
    delete: DeleteStoredObject,
) -> None:
    async with sessions() as session, session.begin():
        document = await session.scalar(
            select(DocumentRow)
            .where(
                DocumentRow.id == file_id,
                DocumentRow.deleted_at.is_(None),
                DocumentRow.status == "ready",
            )
            .with_for_update()
        )
        if document is None:
            raise StorageFileError(StorageFileErrorCode.NOT_FOUND)
        if (
            await session.scalar(
                select(AnalysisDocumentLockRow.job_id).where(
                    AnalysisDocumentLockRow.document_id == document.id
                )
            )
            is not None
        ):
            raise StorageFileError(StorageFileErrorCode.IN_USE)
        if (
            await session.scalar(
                select(CreationMaterialRow.id)
                .where(
                    CreationMaterialRow.document_id == document.id,
                    CreationMaterialRow.owner_hash == document.owner_hash,
                )
                .limit(1)
            )
            is not None
        ):
            raise StorageFileError(StorageFileErrorCode.IN_USE)
        artifacts = tuple(
            await session.scalars(
                select(DocumentArtifactRow)
                .where(
                    DocumentArtifactRow.document_id == document.id,
                    DocumentArtifactRow.deleted_at.is_(None),
                    DocumentArtifactRow.status == "ready",
                )
                .order_by(DocumentArtifactRow.kind)
                .with_for_update()
            )
        )
        for artifact in artifacts:
            await _delete_object(delete, artifact.object_key)
        document.deleted_at = now
        for artifact in artifacts:
            artifact.status = "deleted"
            artifact.deleted_at = now
            artifact.updated_at = now


async def _delete_report(
    sessions: async_sessionmaker[AsyncSession],
    file_id: UUID,
    now: datetime,
    delete: DeleteStoredObject,
) -> None:
    async with sessions() as session, session.begin():
        report = await session.scalar(
            select(AnalysisReportVersionRow)
            .where(
                AnalysisReportVersionRow.id == file_id,
                AnalysisReportVersionRow.status == AnalysisReportStatus.AVAILABLE.value,
            )
            .with_for_update()
        )
        if report is None:
            raise StorageFileError(StorageFileErrorCode.NOT_FOUND)
        artifacts = tuple(
            await session.scalars(
                select(AnalysisReportArtifactRow)
                .where(
                    AnalysisReportArtifactRow.report_id == report.id,
                    AnalysisReportArtifactRow.status
                    == AnalysisReportArtifactStatus.AVAILABLE.value,
                    AnalysisReportArtifactRow.deleted_at.is_(None),
                )
                .order_by(AnalysisReportArtifactRow.format)
                .with_for_update()
            )
        )
        for artifact in artifacts:
            await _delete_object(delete, artifact.object_key)
        report.status = AnalysisReportStatus.DELETED.value
        for artifact in artifacts:
            artifact.status = AnalysisReportArtifactStatus.DELETED.value
            artifact.deleted_at = now


async def _delete_object(delete: DeleteStoredObject, object_key: str) -> None:
    try:
        await delete(object_key)
    except Exception as error:
        raise StorageFileError(StorageFileErrorCode.STORAGE_UNAVAILABLE) from error
