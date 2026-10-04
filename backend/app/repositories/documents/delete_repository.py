"""Crash-recoverable deletion state for screenplay documents."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from app.models import (
    AnalysisDocumentLockRow,
    CreationMaterialRow,
    DocumentArtifactRow,
    DocumentImportAttemptRow,
    DocumentRow,
)
from app.repositories.documents.import_repository_support import current_attempt
from app.repositories.repository_base import RepositoryBase
from app.services.documents.models import DocumentDeletionPlan
from app.services.imports.errors import (
    ImportPersistenceConflict,
    ImportPersistenceNotFound,
)
from app.services.imports.models import ImportCleanupRef
from app.services.imports.rules.enums import ImportStatus


class SqlAlchemyDocumentDeleteRepository(RepositoryBase):
    async def prepare_document_deletion(
        self, document_id: UUID, owner_hash: str, *, now: datetime
    ) -> DocumentDeletionPlan:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(DocumentRow)
                .where(
                    DocumentRow.id == document_id, DocumentRow.owner_hash == owner_hash
                )
                .with_for_update()
            )
            if row is None:
                raise ImportPersistenceNotFound("document does not exist")
            lock = await session.scalar(
                select(AnalysisDocumentLockRow.job_id).where(
                    AnalysisDocumentLockRow.document_id == document_id
                )
            )
            if lock is not None:
                raise ImportPersistenceConflict("document is locked by analysis")
            if (
                await session.scalar(
                    select(CreationMaterialRow.id)
                    .where(
                        CreationMaterialRow.document_id == document_id,
                        CreationMaterialRow.owner_hash == owner_hash,
                    )
                    .limit(1)
                )
                is not None
            ):
                raise ImportPersistenceConflict(
                    "document is retained as a creation source"
                )
            attempt_rows = tuple(
                await session.scalars(
                    select(DocumentImportAttemptRow)
                    .where(DocumentImportAttemptRow.resource_id == document_id)
                    .order_by(DocumentImportAttemptRow.attempt)
                    .with_for_update()
                )
            )
            artifacts = tuple(
                await session.scalars(
                    select(DocumentArtifactRow)
                    .where(
                        DocumentArtifactRow.document_id == document_id,
                        DocumentArtifactRow.status != "deleted",
                    )
                    .order_by(DocumentArtifactRow.kind)
                    .with_for_update()
                )
            )
            if row.deleted_at is None:
                active = await current_attempt(session, row, for_update=True)
                if active is not None and active.status in {
                    ImportStatus.UPLOADING.value,
                    ImportStatus.VERIFYING.value,
                }:
                    active.status = ImportStatus.CANCELLED.value
                    active.error_code = None
                    active.finished_at = now
                    active.updated_at = now
                if row.status in {
                    ImportStatus.UPLOADING.value,
                    ImportStatus.VERIFYING.value,
                }:
                    row.status = ImportStatus.CANCELLED.value
                    row.error_code = None
                    row.finished_at = now
                row.deleted_at = now
                row.version += 1
                row.updated_at = now
            for artifact in artifacts:
                artifact.status = "deleting"
                artifact.updated_at = now
            await session.flush()
            cleanup = tuple(
                ImportCleanupRef(attempt.object_key, attempt.upload_id)
                for attempt in attempt_rows
            ) + tuple(
                ImportCleanupRef(artifact.object_key, None) for artifact in artifacts
            )
            return DocumentDeletionPlan(
                document_id=row.id,
                owner_hash=row.owner_hash,
                attempt=row.attempt,
                cleanup=cleanup,
            )

    async def finish_document_deletion(
        self,
        document_id: UUID,
        owner_hash: str,
        *,
        object_keys: tuple[str, ...],
        now: datetime,
    ) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(DocumentRow)
                .where(
                    DocumentRow.id == document_id, DocumentRow.owner_hash == owner_hash
                )
                .with_for_update()
            )
            if row is None or row.deleted_at is None:
                raise ImportPersistenceNotFound("deleted document does not exist")
            if object_keys:
                artifacts = await session.scalars(
                    select(DocumentArtifactRow)
                    .where(
                        DocumentArtifactRow.document_id == document_id,
                        DocumentArtifactRow.object_key.in_(object_keys),
                    )
                    .with_for_update()
                )
                for artifact in artifacts:
                    artifact.status = "deleted"
                    artifact.deleted_at = now
                    artifact.updated_at = now
            await session.flush()
