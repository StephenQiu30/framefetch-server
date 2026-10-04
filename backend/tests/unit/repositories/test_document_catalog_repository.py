from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from app.models import DocumentArtifactRow, DocumentRow
from app.repositories.documents.catalog_repository import (
    SqlAlchemyDocumentCatalogRepository,
)
from app.repositories.documents.import_repository import (
    SqlAlchemyDocumentImportRepository,
)
from app.schemas.documents import DocumentDetailResponse
from app.services.documents.service import GetDocument, ListDocuments
from app.services.imports.errors import (
    ImportApplicationError,
    ImportApplicationErrorCode,
)
from app.services.imports.models import ImportResourceCreate
from app.services.imports.rules.enums import ContentKind, ImportSourceFormat
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

NOW = datetime(2026, 8, 14, 15, 0, tzinfo=UTC)
FIRST = UUID("66666666-6666-4666-8666-666666666666")
SECOND = UUID("77777777-7777-4777-8777-777777777777")
THIRD = UUID("88888888-8888-4888-8888-888888888888")
OWNER = "a" * 64
OTHER_OWNER = "b" * 64


class FakePreviewStorage:
    def __init__(self, payload: bytes = b"") -> None:
        self.payload = payload
        self.calls: list[tuple[str, int]] = []

    @property
    def bucket(self) -> str:
        return "video-artifacts"

    async def read_range(self, object_key: str, *, length: int) -> bytes:
        self.calls.append((object_key, length))
        return self.payload[:length]


def command(resource_id: UUID, owner_hash: str, key: str) -> ImportResourceCreate:
    return ImportResourceCreate(
        id=resource_id,
        owner_hash=owner_hash,
        idempotency_key=key,
        request_fingerprint=key.ljust(64, "c"),
        content_kind=ContentKind.SCREENPLAY,
        source_format=ImportSourceFormat.MARKDOWN,
        display_name=f"{key}.md",
        content_type=ImportSourceFormat.MARKDOWN.content_type,
        declared_size_bytes=1024,
        declared_sha256="d" * 64,
        rights_statement_version="content-rights",
    )


@pytest.fixture
async def catalog_data(postgres_engine: AsyncEngine):
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    imports = SqlAlchemyDocumentImportRepository(sessions)
    await imports.create_resource(command(FIRST, OWNER, "first"), now=NOW)
    await imports.create_resource(
        command(SECOND, OWNER, "second"), now=NOW + timedelta(seconds=1)
    )
    await imports.create_resource(command(THIRD, OTHER_OWNER, "third"), now=NOW)
    yield SqlAlchemyDocumentCatalogRepository(sessions), sessions


async def test_catalog_is_owner_scoped_ordered_and_hides_deleted(catalog_data) -> None:
    catalog, sessions = catalog_data
    list_documents = ListDocuments(catalog)

    first_page = await list_documents(OWNER, page=1, page_size=1)
    second_page = await list_documents(OWNER, page=2, page_size=1)

    assert first_page.total == second_page.total == 2
    assert first_page.items[0].id == SECOND
    assert second_page.items[0].id == FIRST
    async with sessions() as session, session.begin():
        row = await session.get(DocumentRow, SECOND)
        assert row is not None
        row.deleted_at = NOW + timedelta(minutes=1)
    remaining = await list_documents(OWNER)
    assert remaining.total == 1
    assert tuple(item.id for item in remaining.items) == (FIRST,)


async def test_detail_maps_safe_metadata_and_hides_other_owner(catalog_data) -> None:
    catalog, _ = catalog_data
    storage = FakePreviewStorage()
    get_document = GetDocument(
        catalog, storage, max_preview_bytes=1024, max_preview_characters=100
    )

    view = await get_document(FIRST, OWNER)

    assert view.title == "first"
    assert view.original_filename == "first.md"
    assert view.source_format is ImportSourceFormat.MARKDOWN
    assert view.detected_language is None
    assert view.preview is None and storage.calls == []
    with pytest.raises(ImportApplicationError) as raised:
        await get_document(FIRST, OTHER_OWNER)
    assert raised.value.code is ImportApplicationErrorCode.NOT_FOUND


@pytest.mark.parametrize(
    ("filename", "text", "scene_count"),
    (
        ("screenplay.md", "<script>alert('text only')</script>\n内景 - 夜\n", 1),
        ("document.md", "# 已有文章\n\n原文正文。\n", 0),
    ),
)
async def test_ready_detail_reads_only_bounded_normalized_plain_text(
    catalog_data,
    filename: str,
    text: str,
    scene_count: int,
) -> None:
    catalog, sessions = catalog_data
    payload = text.encode()
    digest = hashlib.sha256(payload).hexdigest()
    async with sessions() as session, session.begin():
        row = await session.get(DocumentRow, FIRST)
        assert row is not None
        row.status = "ready"
        row.attempt = 1
        row.detected_language = "mixed"
        row.scene_count = scene_count
        row.character_count = len(text)
        row.text_sha256 = digest
        row.finished_at = NOW
        session.add(
            DocumentArtifactRow(
                document_id=FIRST,
                kind="normalized",
                bucket="video-artifacts",
                object_key=f"documents/{FIRST}/1/{filename}",
                content_type="text/markdown; charset=utf-8",
                size_bytes=len(payload),
                sha256=digest,
                status="ready",
                artifact_metadata={
                    "parse_summary": {
                        "page_count": 2,
                        "paragraph_count": 3,
                        "heading_count": 1,
                        "list_item_count": 0,
                        "table_count": 0,
                        "dialogue_block_count": 0,
                    }
                },
                created_at=NOW,
                updated_at=NOW,
            )
        )
    storage = FakePreviewStorage(payload)
    view = await GetDocument(
        catalog,
        storage,
        max_preview_bytes=len(payload),
        max_preview_characters=100,
    )(FIRST, OWNER)

    assert view.preview == text
    assert view.preview_truncated is False
    assert view.parse_summary is not None
    assert view.parse_summary.page_count == 2
    assert view.parse_summary.paragraph_count == 3
    assert storage.calls == [(f"documents/{FIRST}/1/{filename}", len(payload))]
    response = DocumentDetailResponse.from_view(view)
    assert response.scene_count == scene_count
    assert response.preview == text


async def test_preview_truncation_drops_only_an_incomplete_utf8_suffix(
    catalog_data,
) -> None:
    catalog, sessions = catalog_data
    payload = "INT. ROOM - DAY\n你好\n".encode()
    digest = hashlib.sha256(payload).hexdigest()
    async with sessions() as session, session.begin():
        row = await session.get(DocumentRow, FIRST)
        assert row is not None
        row.status = "ready"
        row.attempt = 1
        row.detected_language = "mixed"
        row.scene_count = 1
        row.character_count = 20
        row.text_sha256 = digest
        row.finished_at = NOW
        session.add(
            DocumentArtifactRow(
                document_id=FIRST,
                kind="normalized",
                bucket="video-artifacts",
                object_key=f"documents/{FIRST}/1/screenplay.md",
                content_type="text/markdown; charset=utf-8",
                size_bytes=len(payload),
                sha256=digest,
                status="ready",
                artifact_metadata={},
                created_at=NOW,
                updated_at=NOW,
            )
        )
    storage = FakePreviewStorage(payload)
    byte_limit = payload.index("你".encode()) + 1

    view = await GetDocument(
        catalog,
        storage,
        max_preview_bytes=byte_limit,
        max_preview_characters=100,
    )(FIRST, OWNER)

    assert view.preview == "INT. ROOM - DAY\n"
    assert view.preview_truncated is True


async def test_list_rejects_invalid_pagination(catalog_data) -> None:
    catalog, _ = catalog_data

    with pytest.raises(ImportApplicationError) as raised:
        await ListDocuments(catalog)(OWNER, page=0)

    assert raised.value.code is ImportApplicationErrorCode.INVALID_REQUEST
