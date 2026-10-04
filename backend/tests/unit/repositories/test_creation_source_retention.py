"""Source references stop object deletion before any storage mutation."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.models import ArtifactRow, DocumentArtifactRow, DocumentRow
from app.repositories.creation import CreationRepository
from app.repositories.documents.delete_repository import (
    SqlAlchemyDocumentDeleteRepository,
)
from app.repositories.downloads.delete_repository import DownloadDeleteRepository
from app.repositories.errors import RepositoryConflict
from app.repositories.storage_files.repository import SqlAlchemyStorageFileRepository
from app.services.creation.models import CreationMaterialCreateRequest
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
    creation = CreationRepository(sessions)
    material = await creation.create_material(
        OWNER,
        str(uuid4()),
        CreationMaterialCreateRequest(
            kind="video",
            title="固定影视依据",
            download_id=source.download_id,
            rights_statement="本人拥有素材使用权",
        ),
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
    fixed = await creation.get_material(material.id, OWNER)
    assert fixed.artifact_id == source.artifact_id
    assert fixed.current_revision.id == material.current_revision.id


@pytest.mark.asyncio
async def test_historical_document_source_blocks_delete_and_age_cleanup(
    postgres_engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    source = await seed_screenplay(sessions, NOW)
    creation = CreationRepository(sessions)
    # This directly seeds a historical reference. New API intake requires real bytes.
    material = await creation.create_material(
        OWNER,
        str(uuid4()),
        CreationMaterialCreateRequest(
            kind="screenplay",
            title="历史剧本依据",
            text="已保存的剧本文本",
            document_id=source.document_id,
            rights_statement="本人拥有剧本使用权",
        ),
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
    fixed = await creation.get_material(material.id, OWNER)
    assert fixed.document_id == source.document_id
    assert fixed.current_revision.id == material.current_revision.id
