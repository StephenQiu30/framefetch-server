from __future__ import annotations

import re
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import as_utc
from app.models import DocumentImportAttemptRow, DocumentRow
from app.services.documents.rules.screenplay import ScreenplayScene
from app.services.documents.rules.structure import ScreenplayElementKind
from app.services.import_execution.models import (
    ImportVerificationClaim,
    VerifiedDocumentImport,
)
from app.services.imports.errors import (
    ImportPersistenceConflict,
    ImportPersistenceNotFound,
)
from app.services.imports.rules.enums import ContentKind, ImportSourceFormat

_SHA256 = re.compile(r"[0-9a-f]{64}")
_LANGUAGES = {"zh-CN", "en-US", "mixed", "unknown"}
_WARNINGS = {"scene_heading_missing"}


async def lock_document(session: AsyncSession, document_id: UUID) -> DocumentRow:
    row = await session.scalar(
        select(DocumentRow).where(DocumentRow.id == document_id).with_for_update()
    )
    if row is None:
        raise ImportPersistenceNotFound("document does not exist")
    return row


async def lock_attempt(
    session: AsyncSession, document_id: UUID, attempt: int
) -> DocumentImportAttemptRow:
    row = await session.scalar(
        select(DocumentImportAttemptRow)
        .where(
            DocumentImportAttemptRow.resource_id == document_id,
            DocumentImportAttemptRow.attempt == attempt,
        )
        .with_for_update()
    )
    if row is None:
        raise ImportPersistenceConflict("document import attempt does not exist")
    return row


def validate_claim_arguments(
    content_kind: ContentKind,
    attempt: int,
    version: int,
    worker_id: str,
    lease_for: timedelta,
) -> None:
    if (
        content_kind is not ContentKind.SCREENPLAY
        or isinstance(attempt, bool)
        or attempt < 1
        or isinstance(version, bool)
        or version < 1
        or not worker_id.strip()
        or len(worker_id) > 128
        or lease_for.total_seconds() <= 0
    ):
        raise ValueError("invalid document verification claim")


def validate_heartbeat(
    attempt: int,
    worker_id: str,
    stage: str,
    progress: int,
    lease_for: timedelta,
) -> None:
    if (
        isinstance(attempt, bool)
        or attempt < 1
        or not worker_id.strip()
        or len(worker_id) > 128
        or stage not in {"verifying", "uploading"}
        or isinstance(progress, bool)
        or not 0 <= progress <= 100
        or lease_for.total_seconds() <= 0
    ):
        raise ValueError("invalid document verification heartbeat")


def owns(row: DocumentImportAttemptRow, worker_id: str, now: datetime) -> bool:
    return bool(
        row.lease_owner == worker_id
        and row.lease_expires_at is not None
        and as_utc(row.lease_expires_at) > as_utc(now)
    )


def clear_lease(row: DocumentImportAttemptRow, heartbeat: datetime | None) -> None:
    row.lease_owner = None
    row.lease_expires_at = None
    row.heartbeat_at = heartbeat


def verification_claim(
    document: DocumentRow, attempt: DocumentImportAttemptRow
) -> ImportVerificationClaim:
    return ImportVerificationClaim(
        resource_id=document.id,
        content_kind=ContentKind.SCREENPLAY,
        source_format=ImportSourceFormat(document.source_format),
        attempt=attempt.attempt,
        version=document.version,
        object_key=attempt.object_key,
        declared_size_bytes=document.declared_size_bytes,
        declared_sha256=document.declared_sha256,
    )


def artifact_keys(claim: ImportVerificationClaim) -> tuple[str, str]:
    if claim.content_kind is not ContentKind.SCREENPLAY or claim.attempt < 1:
        raise ValueError("invalid document artifact identity")
    prefix = f"documents/{claim.resource_id}/{claim.attempt}"
    return f"{prefix}/original", f"{prefix}/document.md"


def validate_artifact(
    claim: ImportVerificationClaim,
    artifact: VerifiedDocumentImport,
    bucket: str,
) -> None:
    spans_are_valid = all(
        _valid_scene(scene, artifact.character_count) for scene in artifact.scenes
    )
    summary = artifact.parse_summary
    if (
        not bucket.strip()
        or len(bucket) > 128
        or _SHA256.fullmatch(artifact.original_sha256) is None
        or _SHA256.fullmatch(artifact.normalized_sha256) is None
        or artifact.original_sha256 != claim.declared_sha256
        or artifact.original_size_bytes != claim.declared_size_bytes
        or artifact.original_content_type != claim.source_format.content_type
        or artifact.normalized_size_bytes <= 0
        or artifact.character_count <= 0
        or artifact.detected_language not in _LANGUAGES
        or not set(artifact.quality_warnings) <= _WARNINGS
        or summary.paragraph_count <= 0
        or summary.heading_count < 0
        or summary.list_item_count < 0
        or summary.table_count < 0
        or summary.dialogue_block_count < 0
        or (summary.page_count is not None and summary.page_count <= 0)
        or not spans_are_valid
    ):
        raise ValueError("invalid verified document artifacts")


def _valid_scene(scene: ScreenplayScene, character_count: int) -> bool:
    if not (
        scene.id.startswith("scene-")
        and 0 <= scene.start < scene.end <= character_count
    ):
        return False
    previous_end = scene.start
    kinds = set(ScreenplayElementKind)
    for element in scene.elements:
        if (
            element.kind not in kinds
            or not scene.start <= element.start < element.end <= scene.end
            or element.start < previous_end
        ):
            return False
        previous_end = element.end
    return True
