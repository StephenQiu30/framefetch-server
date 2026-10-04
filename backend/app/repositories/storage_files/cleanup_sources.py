from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import (
    AnalysisArtifactLockRow,
    AnalysisDocumentLockRow,
    ArtifactRow,
    CreationMaterialRow,
    DocumentArtifactRow,
    DocumentRow,
    DownloadJobRow,
)
from app.services.storage_files.ports import DeleteStoredObject

CleanupCounts = tuple[int, int, int, int]


async def cleanup_videos(
    sessions: async_sessionmaker[AsyncSession],
    cutoff: datetime,
    now: datetime,
    delete: DeleteStoredObject,
) -> CleanupCounts:
    removed = objects = freed = failed = 0
    excluded: list[UUID] = []
    while True:
        lock = select(AnalysisArtifactLockRow.job_id).where(
            AnalysisArtifactLockRow.artifact_id == ArtifactRow.id
        )
        statement = (
            select(ArtifactRow)
            .where(
                ArtifactRow.deleted_at.is_(None),
                ArtifactRow.created_at < cutoff,
                ~lock.exists(),
                ~select(CreationMaterialRow.id)
                .join(
                    DownloadJobRow,
                    DownloadJobRow.owner_hash == CreationMaterialRow.owner_hash,
                )
                .where(
                    CreationMaterialRow.artifact_id == ArtifactRow.id,
                    DownloadJobRow.id == ArtifactRow.job_id,
                )
                .exists(),
            )
            .order_by(ArtifactRow.created_at, ArtifactRow.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if excluded:
            statement = statement.where(~ArtifactRow.id.in_(excluded))
        async with sessions() as session, session.begin():
            row = await session.scalar(statement)
            if row is None:
                break
            try:
                await delete(row.object_key)
            except Exception:
                failed += 1
                excluded.append(row.id)
                continue
            row.deleted_at = now
            removed += 1
            objects += 1
            freed += row.size_bytes
    return removed, objects, freed, failed


async def cleanup_documents(
    sessions: async_sessionmaker[AsyncSession],
    cutoff: datetime,
    now: datetime,
    delete: DeleteStoredObject,
) -> CleanupCounts:
    removed = objects = freed = failed = 0
    excluded: list[UUID] = []
    while True:
        lock = select(AnalysisDocumentLockRow.job_id).where(
            AnalysisDocumentLockRow.document_id == DocumentRow.id
        )
        statement = (
            select(DocumentRow)
            .where(
                DocumentRow.deleted_at.is_(None),
                DocumentRow.status == "ready",
                DocumentRow.created_at < cutoff,
                ~lock.exists(),
                ~select(CreationMaterialRow.id)
                .where(
                    CreationMaterialRow.document_id == DocumentRow.id,
                    CreationMaterialRow.owner_hash == DocumentRow.owner_hash,
                )
                .exists(),
            )
            .order_by(DocumentRow.created_at, DocumentRow.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if excluded:
            statement = statement.where(~DocumentRow.id.in_(excluded))
        async with sessions() as session, session.begin():
            document = await session.scalar(statement)
            if document is None:
                break
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
            try:
                for artifact in artifacts:
                    await delete(artifact.object_key)
            except Exception:
                failed += 1
                excluded.append(document.id)
                continue
            document.deleted_at = now
            for artifact in artifacts:
                artifact.status = "deleted"
                artifact.deleted_at = now
                artifact.updated_at = now
            removed += 1
            objects += len(artifacts)
            freed += sum(item.size_bytes for item in artifacts)
    return removed, objects, freed, failed
