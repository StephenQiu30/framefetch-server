"""Source references stop object deletion before any storage mutation."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.models import ArtifactRow, DocumentArtifactRow, DocumentRow
from app.models.creation import CreationMaterialRow, CreationRevisionRow
from app.repositories.documents.delete_repository import (
    SqlAlchemyDocumentDeleteRepository,
)
from app.repositories.downloads.delete_repository import DownloadDeleteRepository
from app.repositories.errors import RepositoryConflict
from app.repositories.storage_files.repository import SqlAlchemyStorageFileRepository
from app.services.imports.errors import ImportPersistenceConflict
from app.services.storage_files.errors import StorageFileError, StorageFileErrorCode
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from tests.unit.repositories.analysis.factories import OWNER, seed_artifact
from tests.unit.repositories.analysis.screenplay_factories import seed_screenplay

NOW = datetime(2026, 10, 4, tzinfo=UTC)


@pytest.mark.asyncio
async def test_creation_video_source_blocks_delete_and_age_cleanup(
    postgres_engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    source = await seed_artifact(sessions, NOW)
    material, revision = await historical_reference(
        sessions, artifact_id=source.artifact_id, kind="video"
    )
    with pytest.raises(RepositoryConflict, match="creation source"):
        await DownloadDeleteRepository(sessions).prepare_download_deletion(
            source.download_id, OWNER, now=NOW
        )
    storage = SqlAlchemyStorageFileRepository(sessions)
    delete = AsyncMock()
    with pytest.raises(StorageFileError) as blocked:
        await storage.delete_file(
            category="video", file_id=source.artifact_id, now=NOW, delete=delete
        )
    assert blocked.value.code is StorageFileErrorCode.IN_USE
    empty = await storage.cleanup_before(
        NOW + timedelta(days=1), now=NOW, delete=delete
    )
    assert empty.removed_resources == empty.removed_objects == 0
    delete.assert_not_awaited()

    # Cleanup still removes unreferenced owned resources, keeping the exact source.
    unused = await seed_artifact(sessions, NOW)
    async with sessions() as session:
        unused_artifact = await session.get(ArtifactRow, unused.artifact_id)
        assert unused_artifact is not None
        unused_key = unused_artifact.object_key
    cleaned = await storage.cleanup_before(
        NOW + timedelta(days=1), now=NOW, delete=delete
    )
    assert cleaned.removed_resources == cleaned.removed_objects == 1
    delete.assert_awaited_once_with(unused_key)
    async with sessions() as session:
        retained = await session.get(ArtifactRow, source.artifact_id)
        assert retained is not None and retained.deleted_at is None
    async with sessions() as session:
        fixed = await session.get(CreationMaterialRow, material.id)
        assert fixed is not None and fixed.artifact_id == source.artifact_id
        assert fixed.current_revision_id == revision.id


@pytest.mark.asyncio
async def test_historical_document_source_blocks_delete_and_age_cleanup(
    postgres_engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    source = await seed_screenplay(sessions, NOW)
    material, revision = await historical_reference(
        sessions, document_id=source.document_id, kind="screenplay"
    )
    with pytest.raises(ImportPersistenceConflict, match="creation source"):
        await SqlAlchemyDocumentDeleteRepository(sessions).prepare_document_deletion(
            source.document_id, OWNER, now=NOW
        )
    storage = SqlAlchemyStorageFileRepository(sessions)
    delete = AsyncMock()
    with pytest.raises(StorageFileError) as blocked:
        await storage.delete_file(
            category="screenplay", file_id=source.document_id, now=NOW, delete=delete
        )
    assert blocked.value.code is StorageFileErrorCode.IN_USE
    empty = await storage.cleanup_before(
        NOW + timedelta(days=1), now=NOW, delete=delete
    )
    assert empty.removed_resources == empty.removed_objects == 0
    delete.assert_not_awaited()

    unused = await seed_screenplay(sessions, NOW)
    async with sessions() as session:
        unused_key = await session.scalar(
            select(DocumentArtifactRow.object_key).where(
                DocumentArtifactRow.document_id == unused.document_id
            )
        )
    cleaned = await storage.cleanup_before(
        NOW + timedelta(days=1), now=NOW, delete=delete
    )
    assert cleaned.removed_resources == cleaned.removed_objects == 1
    delete.assert_awaited_once_with(unused_key)
    async with sessions() as session:
        retained = await session.get(DocumentRow, source.document_id)
        assert retained is not None and retained.deleted_at is None
        assert retained.status == "ready"
        artifacts = tuple(
            await session.scalars(
                select(DocumentArtifactRow).where(
                    DocumentArtifactRow.document_id == source.document_id
                )
            )
        )
        assert artifacts
        assert all(
            item.status == "ready" and item.deleted_at is None for item in artifacts
        )
    async with sessions() as session:
        fixed = await session.get(CreationMaterialRow, material.id)
        assert fixed is not None and fixed.document_id == source.document_id
        assert fixed.current_revision_id == revision.id


async def historical_reference(
    sessions: async_sessionmaker,
    *,
    kind: str,
    artifact_id=None,
    document_id=None,
):
    """Seed only retained historical rows; the retired API is unavailable."""
    material_id, revision_id = uuid4(), uuid4()
    material = CreationMaterialRow(
        id=material_id,
        owner_hash=OWNER,
        idempotency_key=str(uuid4()),
        request_sha256="a" * 64,
        kind=kind,
        title="历史引用",
        rights_statement="本人素材",
        artifact_id=artifact_id,
        document_id=document_id,
        current_revision_id=revision_id,
        created_at=NOW,
        updated_at=NOW,
    )
    revision = CreationRevisionRow(
        id=revision_id,
        material_id=material_id,
        owner_hash=OWNER,
        number=1,
        text="历史内容",
        data={},
        sha256="b" * 64,
        confirmed=True,
        created_at=NOW,
    )
    async with sessions() as session, session.begin():
        session.add(material)
        await session.flush()
        session.add(revision)
    return material, revision
