"""Guards and locked reads shared by document import state transitions."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import as_utc
from app.models import DocumentImportAttemptRow, DocumentRow
from app.services.imports.errors import (
    ImportPersistenceConflict,
    ImportPersistenceNotFound,
)
from app.services.imports.models import ImportResourceCreate
from app.services.imports.rules.enums import ContentKind


def require_document_create(command: ImportResourceCreate) -> None:
    if (
        command.content_kind is not ContentKind.SCREENPLAY
        or command.source_format.content_kind is not ContentKind.SCREENPLAY
        or command.content_type != command.source_format.content_type
    ):
        raise ImportPersistenceConflict(
            "document repository only accepts supported screenplay resources"
        )


def require_document_kind(content_kind: ContentKind) -> None:
    if content_kind is not ContentKind.SCREENPLAY:
        raise ImportPersistenceNotFound("document does not exist")


def validate_part_plan(
    part_size_bytes: int, part_count: int, expires_at: datetime, now: datetime
) -> None:
    if (
        isinstance(part_size_bytes, bool)
        or not 5 * 1024**2 <= part_size_bytes <= 5 * 1024**3
        or isinstance(part_count, bool)
        or not 1 <= part_count <= 10_000
        or as_utc(expires_at) <= as_utc(now)
    ):
        raise ImportPersistenceConflict("invalid document upload part plan")


def valid_upload_id(upload_id: str) -> bool:
    return (
        bool(upload_id)
        and len(upload_id) <= 1024
        and all(ord(character) >= 0x20 for character in upload_id)
    )


async def lock_resource(
    session: AsyncSession, resource_id: UUID, owner_hash: str
) -> DocumentRow:
    row = await session.scalar(
        select(DocumentRow)
        .where(DocumentRow.id == resource_id, DocumentRow.owner_hash == owner_hash)
        .with_for_update()
    )
    if row is None:
        raise ImportPersistenceNotFound("document does not exist")
    return row


async def lock_attempt(
    session: AsyncSession, resource: DocumentRow, attempt: int
) -> DocumentImportAttemptRow:
    row = await session.scalar(
        select(DocumentImportAttemptRow)
        .where(
            DocumentImportAttemptRow.resource_id == resource.id,
            DocumentImportAttemptRow.attempt == attempt,
        )
        .with_for_update()
    )
    if row is None:
        raise ImportPersistenceConflict("document import attempt does not exist")
    return row


async def current_attempt(
    session: AsyncSession, resource: DocumentRow, *, for_update: bool = False
) -> DocumentImportAttemptRow | None:
    if resource.attempt <= 0:
        return None
    statement: Select[tuple[DocumentImportAttemptRow]] = select(
        DocumentImportAttemptRow
    ).where(
        DocumentImportAttemptRow.resource_id == resource.id,
        DocumentImportAttemptRow.attempt == resource.attempt,
    )
    if for_update:
        statement = statement.with_for_update()
    return cast(DocumentImportAttemptRow | None, await session.scalar(statement))
