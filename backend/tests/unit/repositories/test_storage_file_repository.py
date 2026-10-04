from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models import (
    AnalysisArtifactLockRow,
    AnalysisJobRow,
    AnalysisReportArtifactRow,
    AnalysisReportVersionRow,
    AnalysisRunRow,
    ArtifactRow,
    UserRow,
)
from app.repositories.storage_files.repository import SqlAlchemyStorageFileRepository
from app.services.auth.models import CurrentUser, UserRole
from app.services.storage_files.errors import StorageFileError, StorageFileErrorCode
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from tests.unit.repositories.analysis.factories import seed_artifact
from tests.unit.repositories.analysis.screenplay_factories import seed_screenplay
from tests.unit.repositories.analytics_helpers import add_browser_import, add_job

NOW = datetime(2026, 8, 18, 12, tzinfo=UTC)
OWNER = "a" * 64


@pytest.mark.asyncio
async def test_storage_files_resolve_uploaders_for_each_resource_and_keep_orphans(
    postgres_engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    uploader = CurrentUser(
        id=uuid4(),
        username="video_owner",
        email="video@example.com",
        role=UserRole.USER,
        created_at=NOW,
        updated_at=NOW,
    )
    author = CurrentUser(
        id=uuid4(),
        username="report_author",
        email="author@example.com",
        role=UserRole.USER,
        created_at=NOW,
        updated_at=NOW,
    )
    async with sessions.begin() as session:
        for user in (uploader, author):
            session.add(
                UserRow(
                    id=user.id,
                    username=user.username,
                    normalized_username=user.username,
                    email=user.email,
                    password_hash="controlled-test-hash",
                    role="user",
                    is_active=user.id == uploader.id,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )

    video = await seed_artifact(sessions, NOW, owner_hash=uploader.owner_hash)
    await add_browser_import(
        sessions,
        owner=uploader.owner_hash,
        created_at=NOW,
        duration_ms=30_000,
        size_bytes=2_048,
    )
    document = await seed_screenplay(sessions, NOW, owner_hash=author.owner_hash)
    await add_job(
        sessions,
        extractor="Controlled",
        owner=OWNER,
        status="succeeded",
        created_at=NOW,
        duration=30,
        size_bytes=512,
    )
    job_id, run_id, report_id = uuid4(), uuid4(), uuid4()
    async with sessions.begin() as session:
        session.add(
            AnalysisJobRow(
                id=job_id,
                artifact_id=video.artifact_id,
                owner_hash=author.owner_hash,
                idempotency_key="uploader-report",
                request_fingerprint="e" * 64,
                input_sha256=video.sha256,
                skill_id="director-breakdown",
                skill_instructions="controlled",
                skill_instructions_sha256="f" * 64,
                output_language="zh-CN",
                status="succeeded",
                progress=100,
                active_run_id=run_id,
                current_report_id=report_id,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        session.add(
            AnalysisRunRow(
                id=run_id,
                job_id=job_id,
                run_no=1,
                trigger="initial",
                status="succeeded",
                progress=100,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        session.add(
            AnalysisReportVersionRow(
                id=report_id,
                job_id=job_id,
                run_id=run_id,
                input_sha256=video.sha256,
                language="zh-CN",
                result_json={"kind": "video_visual_analysis"},
                report_markdown="# Controlled report",
                content_sha256="a" * 64,
                renderer_version="controlled",
                provider="controlled",
                model="controlled",
                cli_version="controlled",
                status="available",
                created_at=NOW,
                published_at=NOW,
            )
        )
        await session.flush()
        for format_, size in (("markdown", 100), ("docx", 200)):
            session.add(
                AnalysisReportArtifactRow(
                    id=uuid4(),
                    report_id=report_id,
                    format=format_,
                    bucket="controlled",
                    object_key=f"reports/{report_id}/{format_}",
                    content_type="application/octet-stream",
                    size_bytes=size,
                    sha256="a" * 64,
                    status="available",
                    created_at=NOW,
                    available_at=NOW,
                )
            )

    repository = SqlAlchemyStorageFileRepository(sessions)
    page = await repository.list_files(page=1, page_size=20)
    assert page.total == len(page.items) == 5
    by_id = {item.id: item for item in page.items}
    assert by_id[video.artifact_id].uploader_username == uploader.username
    assert by_id[document.document_id].uploader_username == author.username
    assert by_id[report_id].uploader_username == author.username
    assert by_id[report_id].object_count == 2
    assert by_id[report_id].size_bytes == 300
    assert sum(item.uploader_username is None for item in page.items) == 1
    assert sum(item.uploader_username == uploader.username for item in page.items) == 2
    # Resolve the current username, including disabled accounts; do not store a copy.
    async with sessions.begin() as session:
        account = await session.get(UserRow, author.id)
        assert account is not None
        account.username = "renamed_author"
    renamed = await repository.list_files(page=1, page_size=20)
    assert {
        item.uploader_username
        for item in renamed.items
        if item.id in {document.document_id, report_id}
    } == {"renamed_author"}
    async with sessions.begin() as session:
        await session.execute(delete(UserRow).where(UserRow.id == author.id))
    remaining = await repository.list_files(page=1, page_size=20)
    assert remaining.total == 5
    assert all(
        item.uploader_username is None
        for item in remaining.items
        if item.id in {document.document_id, report_id}
    )


@pytest.mark.asyncio
async def test_storage_files_page_and_manual_cleanup_respect_analysis_lock(
    postgres_engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    await add_job(
        sessions,
        extractor="Youtube",
        owner=OWNER,
        status="succeeded",
        created_at=NOW - timedelta(days=31),
        duration=30,
        size_bytes=1_024,
    )
    await add_job(
        sessions,
        extractor="Vimeo",
        owner=OWNER,
        status="succeeded",
        created_at=NOW - timedelta(days=5),
        duration=45,
        size_bytes=2_048,
    )
    async with sessions() as session, session.begin():
        old_artifact = await session.scalar(
            select(ArtifactRow).order_by(ArtifactRow.created_at)
        )
        assert old_artifact is not None
        old_artifact_id = old_artifact.id
        analysis_id, run_id = uuid4(), uuid4()
        session.add(
            AnalysisJobRow(
                id=analysis_id,
                artifact_id=old_artifact.id,
                owner_hash=OWNER,
                idempotency_key="locked-analysis",
                request_fingerprint="e" * 64,
                input_sha256=old_artifact.sha256,
                skill_id="director-breakdown",
                skill_instructions="controlled",
                skill_instructions_sha256="f" * 64,
                output_language="zh-CN",
                status="running",
                progress=10,
                active_run_id=run_id,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        session.add(
            AnalysisArtifactLockRow(
                job_id=analysis_id,
                artifact_id=old_artifact.id,
                created_at=NOW,
            )
        )

    repository = SqlAlchemyStorageFileRepository(sessions)
    first_page = await repository.list_files(page=1, page_size=1)
    second_page = await repository.list_files(page=2, page_size=1)
    assert first_page.total == second_page.total == 2
    assert first_page.items[0].size_bytes == 2_048
    assert second_page.items[0].size_bytes == 1_024

    deleted: list[str] = []

    async def delete_object(key: str) -> None:
        deleted.append(key)

    locked = await repository.cleanup_before(
        NOW - timedelta(days=30), now=NOW, delete=delete_object
    )
    assert locked.removed_resources == 0
    assert deleted == []

    with pytest.raises(StorageFileError) as error:
        await repository.delete_file(
            category="video",
            file_id=old_artifact_id,
            now=NOW,
            delete=delete_object,
        )
    assert error.value.code is StorageFileErrorCode.IN_USE

    async with sessions() as session, session.begin():
        await session.execute(delete(AnalysisArtifactLockRow))
    cleaned = await repository.cleanup_before(
        NOW - timedelta(days=30), now=NOW, delete=delete_object
    )
    assert cleaned.removed_resources == cleaned.removed_objects == 1
    assert cleaned.freed_bytes == 1_024
    assert cleaned.failed_resources == 0
    assert len(deleted) == 1
    remaining = await repository.list_files(page=1, page_size=20)
    assert remaining.total == 1
    assert remaining.items[0].size_bytes == 2_048

    await repository.delete_file(
        category="video",
        file_id=remaining.items[0].id,
        now=NOW,
        delete=delete_object,
    )
    assert len(deleted) == 2
    assert (await repository.list_files(page=1, page_size=20)).total == 0
