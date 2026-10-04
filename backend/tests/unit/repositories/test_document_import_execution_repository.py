from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from app.models import (
    DocumentArtifactRow,
    DocumentImportAttemptRow,
    DocumentRow,
    OutboxEventRow,
)
from app.repositories.documents.import_execution_repository import (
    SqlAlchemyDocumentImportExecutionRepository,
)
from app.repositories.documents.import_repository import (
    SqlAlchemyDocumentImportRepository,
)
from app.services.documents.rules.screenplay import ScreenplayScene
from app.services.documents.rules.structure import (
    ScreenplayElement,
    ScreenplayElementKind,
)
from app.services.documents.rules.summary import DocumentParseSummary
from app.services.import_execution.models import VerifiedDocumentImport
from app.services.imports.models import ImportResourceCreate
from app.services.imports.rules.enums import (
    ContentKind,
    ImportErrorCode,
    ImportSourceFormat,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

NOW = datetime(2026, 8, 14, 18, 0, tzinfo=UTC)
DOCUMENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OWNER = "a" * 64


@pytest.fixture
async def repositories(postgres_engine: AsyncEngine):
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    yield (
        SqlAlchemyDocumentImportRepository(sessions),
        SqlAlchemyDocumentImportExecutionRepository(sessions),
        sessions,
    )


async def verifying(upload_repository):
    await upload_repository.create_resource(
        ImportResourceCreate(
            id=DOCUMENT_ID,
            owner_hash=OWNER,
            idempotency_key="document-execution",
            request_fingerprint="b" * 64,
            content_kind=ContentKind.SCREENPLAY,
            source_format=ImportSourceFormat.FOUNTAIN,
            display_name="story.fountain",
            content_type=ImportSourceFormat.FOUNTAIN.content_type,
            declared_size_bytes=128,
            declared_sha256="c" * 64,
            rights_statement_version="content-rights",
        ),
        now=NOW,
    )
    begun = await upload_repository.begin_upload_attempt(
        DOCUMENT_ID,
        OWNER,
        ContentKind.SCREENPLAY,
        part_size_bytes=5 * 1024**2,
        part_count=1,
        expires_at=NOW + timedelta(minutes=15),
        now=NOW,
    )
    await upload_repository.activate_upload_attempt(
        DOCUMENT_ID,
        OWNER,
        ContentKind.SCREENPLAY,
        begun.attempt.attempt,
        upload_id="upload-1",
        now=NOW,
    )
    return await upload_repository.mark_verifying(
        DOCUMENT_ID,
        OWNER,
        ContentKind.SCREENPLAY,
        begun.attempt.attempt,
        actual_size_bytes=128,
        now=NOW,
    )


def verified(path: Path) -> VerifiedDocumentImport:
    return VerifiedDocumentImport(
        original_sha256="c" * 64,
        original_size_bytes=128,
        original_content_type=ImportSourceFormat.FOUNTAIN.content_type,
        normalized_path=path,
        normalized_sha256="d" * 64,
        normalized_size_bytes=64,
        detected_language="en-US",
        character_count=64,
        scenes=(
            ScreenplayScene(
                "scene-0001-123456789abc",
                0,
                64,
                (
                    ScreenplayElement(ScreenplayElementKind.HEADING, 0, 16),
                    ScreenplayElement(ScreenplayElementKind.ACTION, 17, 64),
                ),
            ),
        ),
        quality_warnings=(),
        parse_summary=DocumentParseSummary(None, 2, 1, 0, 0, 0),
    )


async def test_claim_heartbeat_and_completion_create_two_immutable_artifacts(
    repositories, tmp_path: Path
) -> None:
    upload, execution, sessions = repositories
    resource = await verifying(upload)
    claim = await execution.claim_verification(
        DOCUMENT_ID,
        ContentKind.SCREENPLAY,
        1,
        resource.version,
        worker_id="worker-a",
        now=NOW,
        lease_for=timedelta(seconds=30),
    )
    assert claim is not None
    assert await execution.heartbeat_verification(
        DOCUMENT_ID,
        1,
        worker_id="worker-a",
        stage="uploading",
        progress=95,
        now=NOW + timedelta(seconds=1),
        lease_for=timedelta(seconds=30),
    )
    artifact = verified(tmp_path / "screenplay.md")
    await execution.complete_verification(
        claim,
        artifact,
        worker_id="worker-a",
        bucket="video-artifacts",
        now=NOW + timedelta(seconds=2),
    )
    await execution.complete_verification(
        claim,
        artifact,
        worker_id="worker-a",
        bucket="video-artifacts",
        now=NOW + timedelta(seconds=3),
    )

    async with sessions() as session:
        document = await session.get(DocumentRow, DOCUMENT_ID)
        attempt = await session.get(DocumentImportAttemptRow, (DOCUMENT_ID, 1))
        artifacts = tuple(
            (
                await session.scalars(
                    select(DocumentArtifactRow).order_by(DocumentArtifactRow.kind)
                )
            ).all()
        )
    assert document is not None and document.status == "ready"
    assert document.text_sha256 == "d" * 64
    assert document.scene_count == 1 and document.character_count == 64
    assert attempt is not None and attempt.status == "ready"
    assert [item.kind for item in artifacts] == ["normalized", "original"]
    assert artifacts[0].artifact_metadata["scenes"][0]["id"].startswith("scene-")
    assert artifacts[0].artifact_metadata["scenes"][0]["elements"] == [
        {"kind": "heading", "start": 0, "end": 16},
        {"kind": "action", "start": 17, "end": 64},
    ]
    assert artifacts[0].artifact_metadata["parse_summary"] == {
        "page_count": None,
        "paragraph_count": 2,
        "heading_count": 1,
        "list_item_count": 0,
        "table_count": 0,
        "dialogue_block_count": 0,
    }


async def test_completion_rejects_overlapping_structure_offsets(
    repositories, tmp_path: Path
) -> None:
    upload, execution, _ = repositories
    resource = await verifying(upload)
    claim = await execution.claim_verification(
        DOCUMENT_ID,
        ContentKind.SCREENPLAY,
        1,
        resource.version,
        worker_id="worker-a",
        now=NOW,
        lease_for=timedelta(seconds=30),
    )
    assert claim is not None
    invalid = replace(
        verified(tmp_path / "screenplay.md"),
        scenes=(
            ScreenplayScene(
                "scene-0001-123456789abc",
                0,
                64,
                (
                    ScreenplayElement(ScreenplayElementKind.HEADING, 0, 16),
                    ScreenplayElement(ScreenplayElementKind.ACTION, 15, 64),
                ),
            ),
        ),
    )

    with pytest.raises(ValueError, match="invalid verified document artifacts"):
        await execution.complete_verification(
            claim,
            invalid,
            worker_id="worker-a",
            bucket="video-artifacts",
            now=NOW + timedelta(seconds=1),
        )


async def test_terminal_failure_and_expired_lease_recovery_are_stable(
    repositories,
) -> None:
    upload, execution, sessions = repositories
    resource = await verifying(upload)
    claim = await execution.claim_verification(
        DOCUMENT_ID,
        ContentKind.SCREENPLAY,
        1,
        resource.version,
        worker_id="worker-a",
        now=NOW,
        lease_for=timedelta(seconds=30),
    )
    assert claim is not None
    recovered = await execution.recover_expired_verifications(
        NOW + timedelta(seconds=31), limit=10
    )
    assert recovered == (DOCUMENT_ID,)
    reclaimed = await execution.claim_verification(
        DOCUMENT_ID,
        ContentKind.SCREENPLAY,
        1,
        resource.version,
        worker_id="worker-b",
        now=NOW + timedelta(seconds=31),
        lease_for=timedelta(seconds=30),
    )
    assert reclaimed is not None
    await execution.fail_verification(
        reclaimed,
        ImportErrorCode.DOCUMENT_TEXT_UNAVAILABLE,
        worker_id="worker-b",
        now=NOW + timedelta(seconds=32),
    )

    async with sessions() as session:
        document = await session.get(DocumentRow, DOCUMENT_ID)
        events = await session.scalar(select(func.count(OutboxEventRow.id)))
    assert document is not None and document.status == "failed"
    assert document.error_code == ImportErrorCode.DOCUMENT_TEXT_UNAVAILABLE.value
    assert events == 2


async def test_ordinary_document_with_no_scenes_is_published_ready(
    repositories, tmp_path
):
    upload, execution, sessions = repositories
    resource = await verifying(upload)
    claim = await execution.claim_verification(
        DOCUMENT_ID,
        ContentKind.SCREENPLAY,
        1,
        resource.version,
        worker_id="ordinary",
        now=NOW,
        lease_for=timedelta(seconds=30),
    )
    ordinary = replace(
        verified(tmp_path / "document.md"),
        scenes=(),
        quality_warnings=(),
        parse_summary=DocumentParseSummary(None, 2, 0, 0, 0, 0),
    )
    await execution.complete_verification(
        claim,
        ordinary,
        worker_id="ordinary",
        bucket="video-artifacts",
        now=NOW + timedelta(seconds=1),
    )
    async with sessions() as session:
        document = await session.get(DocumentRow, DOCUMENT_ID)
        assert document.status == "ready" and document.scene_count == 0
        assert document.character_count == 64 and document.text_sha256 == "d" * 64
        normalized = await session.scalar(
            select(DocumentArtifactRow).where(
                DocumentArtifactRow.document_id == DOCUMENT_ID,
                DocumentArtifactRow.kind == "normalized",
            )
        )
        assert normalized.artifact_metadata["scenes"] == []
        assert normalized.object_key.endswith("/document.md")
