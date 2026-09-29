"""Validate and retain immutable video or screenplay analysis inputs."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AnalysisArtifactLockRow,
    AnalysisDocumentLockRow,
    AnalysisJobRow,
    ArtifactRow,
    DocumentArtifactRow,
    DocumentRow,
    DownloadJobRow,
)
from app.services.analysis.errors import (
    PersistenceArtifactUnavailable,
    PersistenceConflict,
    PersistenceNotFound,
)
from app.services.analysis.models import AnalysisCreate
from app.services.analysis.rules.contracts import contracts_for_input
from app.services.analysis.rules.enums import AnalysisInputKind

_SCREENPLAY_CONTRACTS = contracts_for_input(AnalysisInputKind.SCREENPLAY)
_VIDEO_CONTRACTS = contracts_for_input(AnalysisInputKind.VIDEO)


async def validate_create_source(
    session: AsyncSession, command: AnalysisCreate, now: datetime
) -> None:
    if (
        command.input_kind is AnalysisInputKind.VIDEO
        and command.result_contract in _VIDEO_CONTRACTS
        and command.artifact_id is not None
        and command.document_id is None
    ):
        artifact = await _video_source(
            session, command.artifact_id, command.owner_hash, now
        )
        if artifact is None:
            raise PersistenceNotFound("analysis artifact is unavailable")
        if artifact.sha256 != command.input_sha256:
            raise PersistenceConflict("analysis input SHA changed")
        return
    if (
        command.input_kind is AnalysisInputKind.SCREENPLAY
        and command.result_contract in _SCREENPLAY_CONTRACTS
        and command.document_id is not None
        and command.artifact_id is None
    ):
        source = await _screenplay_source(
            session, command.document_id, command.owner_hash, now
        )
        if source is None:
            raise PersistenceNotFound("analysis document is unavailable")
        document, normalized = source
        if (
            document.text_sha256 != command.input_sha256
            or normalized.sha256 != command.input_sha256
        ):
            raise PersistenceConflict("analysis input SHA changed")
        return
    raise PersistenceNotFound("analysis source shape is invalid")


async def require_retry_source(
    session: AsyncSession, row: AnalysisJobRow, now: datetime
) -> None:
    if (
        row.input_kind == AnalysisInputKind.VIDEO.value
        and row.result_contract in {contract.value for contract in _VIDEO_CONTRACTS}
        and row.artifact_id is not None
        and row.document_id is None
    ):
        artifact = await _video_source(session, row.artifact_id, row.owner_hash, now)
        if artifact is not None and artifact.sha256 == row.input_sha256:
            return
    elif (
        row.input_kind == AnalysisInputKind.SCREENPLAY.value
        and row.result_contract
        in {contract.value for contract in _SCREENPLAY_CONTRACTS}
        and row.document_id is not None
        and row.artifact_id is None
    ):
        source = await _screenplay_source(session, row.document_id, row.owner_hash, now)
        if source is not None:
            document, normalized = source
            if (
                document.text_sha256 == row.input_sha256
                and normalized.sha256 == row.input_sha256
            ):
                return
    raise PersistenceArtifactUnavailable("analysis input is unavailable")


def new_source_lock(
    row: AnalysisJobRow, now: datetime
) -> AnalysisArtifactLockRow | AnalysisDocumentLockRow:
    if row.input_kind == AnalysisInputKind.VIDEO.value and row.artifact_id is not None:
        return AnalysisArtifactLockRow(
            job_id=row.id, artifact_id=row.artifact_id, created_at=now
        )
    if (
        row.input_kind == AnalysisInputKind.SCREENPLAY.value
        and row.document_id is not None
    ):
        return AnalysisDocumentLockRow(
            job_id=row.id, document_id=row.document_id, created_at=now
        )
    raise PersistenceArtifactUnavailable("analysis input shape is invalid")


async def release_source_locks(session: AsyncSession, job_id: UUID) -> None:
    for lock_row in (AnalysisArtifactLockRow, AnalysisDocumentLockRow):
        await session.execute(delete(lock_row).where(lock_row.job_id == job_id))


async def _video_source(
    session: AsyncSession, artifact_id: UUID, owner_hash: str, now: datetime
) -> ArtifactRow | None:
    return cast(
        ArtifactRow | None,
        await session.scalar(
            select(ArtifactRow)
            .join(DownloadJobRow, DownloadJobRow.id == ArtifactRow.job_id)
            .where(
                ArtifactRow.id == artifact_id,
                ArtifactRow.deleted_at.is_(None),
                DownloadJobRow.owner_hash == owner_hash,
                DownloadJobRow.status == "succeeded",
            )
            .with_for_update()
        ),
    )


async def _screenplay_source(
    session: AsyncSession, document_id: UUID, owner_hash: str, now: datetime
) -> tuple[DocumentRow, DocumentArtifactRow] | None:
    result = (
        await session.execute(
            select(DocumentRow, DocumentArtifactRow)
            .join(
                DocumentArtifactRow,
                DocumentArtifactRow.document_id == DocumentRow.id,
            )
            .where(
                DocumentRow.id == document_id,
                DocumentRow.owner_hash == owner_hash,
                DocumentRow.status == "ready",
                DocumentRow.deleted_at.is_(None),
                DocumentArtifactRow.kind == "normalized",
                DocumentArtifactRow.status == "ready",
                DocumentArtifactRow.deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).one_or_none()
    if result is None:
        return None
    return result[0], result[1]
