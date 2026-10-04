from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from app.models import DocumentArtifactRow, DocumentImportAttemptRow, DocumentRow
from app.repositories.documents.catalog_repository import (
    SqlAlchemyDocumentCatalogRepository,
)
from app.repositories.documents.delete_repository import (
    SqlAlchemyDocumentDeleteRepository,
)
from app.repositories.documents.import_repository import (
    SqlAlchemyDocumentImportRepository,
)
from app.services.documents.service import DeleteDocument
from app.services.imports.errors import ImportApplicationError
from app.services.imports.models import ImportResourceCreate
from app.services.imports.rules.enums import (
    ContentKind,
    ImportSourceFormat,
    ImportStatus,
)
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

NOW = datetime(2026, 8, 14, 16, 0, tzinfo=UTC)
DOCUMENT_ID = UUID("99999999-9999-4999-8999-999999999999")
ORIGINAL_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
NORMALIZED_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
OWNER = "a" * 64


class FakeStorage:
    def __init__(self) -> None:
        self.aborted: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    async def abort_multipart_upload(self, object_key: str, upload_id: str) -> None:
        self.aborted.append((object_key, upload_id))

    async def delete(self, object_key: str) -> None:
        self.deleted.append(object_key)


def command() -> ImportResourceCreate:
    return ImportResourceCreate(
        id=DOCUMENT_ID,
        owner_hash=OWNER,
        idempotency_key="delete-document",
        request_fingerprint="b" * 64,
        content_kind=ContentKind.SCREENPLAY,
        source_format=ImportSourceFormat.TXT,
        display_name="delete.txt",
        content_type=ImportSourceFormat.TXT.content_type,
        declared_size_bytes=1024,
        declared_sha256="c" * 64,
        rights_statement_version="content-rights",
    )


@pytest.fixture(params=("screenplay.md", "document.md"))
async def deletion_data(postgres_engine: AsyncEngine, request):
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    imports = SqlAlchemyDocumentImportRepository(sessions)
    await imports.create_resource(command(), now=NOW)
    await imports.begin_upload_attempt(
        DOCUMENT_ID,
        OWNER,
        ContentKind.SCREENPLAY,
        part_size_bytes=5 * 1024**2,
        part_count=1,
        expires_at=NOW + timedelta(minutes=15),
        now=NOW,
    )
    await imports.activate_upload_attempt(
        DOCUMENT_ID,
        OWNER,
        ContentKind.SCREENPLAY,
        1,
        upload_id="delete-upload",
        now=NOW,
    )
    async with sessions() as session, session.begin():
        session.add_all(
            (
                DocumentArtifactRow(
                    id=ORIGINAL_ID,
                    document_id=DOCUMENT_ID,
                    kind="original",
                    bucket="video-artifacts",
                    object_key=f"documents/{DOCUMENT_ID}/1/original",
                    content_type="text/plain; charset=utf-8",
                    size_bytes=1024,
                    sha256="c" * 64,
                    status="ready",
                    artifact_metadata={},
                    created_at=NOW,
                    updated_at=NOW,
                ),
                DocumentArtifactRow(
                    id=NORMALIZED_ID,
                    document_id=DOCUMENT_ID,
                    kind="normalized",
                    bucket="video-artifacts",
                    object_key=f"documents/{DOCUMENT_ID}/1/{request.param}",
                    content_type="text/markdown; charset=utf-8",
                    size_bytes=900,
                    sha256="d" * 64,
                    status="ready",
                    artifact_metadata={},
                    created_at=NOW,
                    updated_at=NOW,
                ),
            )
        )
    yield sessions, request.param


async def test_delete_marks_state_cleans_objects_and_is_retryable(
    deletion_data,
) -> None:
    sessions, filename = deletion_data
    storage = FakeStorage()
    service = DeleteDocument(
        SqlAlchemyDocumentDeleteRepository(sessions), storage, now=lambda: NOW
    )

    await service(DOCUMENT_ID, OWNER)
    await service(DOCUMENT_ID, OWNER)

    quarantine = f"quarantine/screenplay/{DOCUMENT_ID}/1/source"
    assert storage.aborted == [(quarantine, "delete-upload")] * 2
    assert set(storage.deleted) == {
        quarantine,
        f"documents/{DOCUMENT_ID}/1/original",
        f"documents/{DOCUMENT_ID}/1/{filename}",
    }
    async with sessions() as session:
        document = await session.get(DocumentRow, DOCUMENT_ID)
        attempt = await session.get(DocumentImportAttemptRow, (DOCUMENT_ID, 1))
        original = await session.get(DocumentArtifactRow, ORIGINAL_ID)
    assert document is not None and document.deleted_at is not None
    assert document.status == ImportStatus.CANCELLED.value
    assert attempt is not None and attempt.status == ImportStatus.CANCELLED.value
    assert original is not None and original.status == "deleted"
    assert original.deleted_at == NOW
    assert (
        await SqlAlchemyDocumentCatalogRepository(sessions).get_document(
            DOCUMENT_ID, OWNER
        )
        is None
    )


async def test_delete_rejects_untrusted_artifact_key(deletion_data) -> None:
    sessions, _ = deletion_data
    async with sessions() as session, session.begin():
        artifact = await session.get(DocumentArtifactRow, ORIGINAL_ID)
        assert artifact is not None
        artifact.object_key = "documents/another-owner/1/original"
    storage = FakeStorage()

    with pytest.raises(ImportApplicationError):
        await DeleteDocument(
            SqlAlchemyDocumentDeleteRepository(sessions), storage, now=lambda: NOW
        )(DOCUMENT_ID, OWNER)

    assert storage.deleted == []
