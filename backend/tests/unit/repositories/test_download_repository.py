from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models import (
    ArtifactRow,
    DownloadJobRow,
    DownloadThumbnailRow,
    MediaImportAttemptRow,
    MediaImportRow,
    MediaInspectionRow,
)
from app.repositories.contracts import ArtifactCreate
from app.repositories.downloads.repository import SqlAlchemyDownloadRepository
from app.repositories.errors import LeaseConflict
from app.services.downloads.download_models import (
    DownloadCreate as ApplicationDownloadCreate,
)
from app.services.downloads.history import (
    GetDownloadHistory as ApplicationGetDownloadHistory,
)
from app.services.downloads.inspection_models import (
    FormatCreate as ApplicationFormatCreate,
)
from app.services.downloads.inspection_models import (
    InspectionCreate as ApplicationInspectionCreate,
)
from app.services.downloads.thumbnail import (
    ThumbnailObject as ApplicationThumbnailObject,
)
from app.services.provider_types import ExecutionContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

NOW = datetime(2026, 8, 6, tzinfo=UTC)


@pytest.mark.asyncio
async def test_download_repository_handles_the_complete_application_lifecycle(
    postgres_engine: AsyncEngine,
) -> None:
    repository = SqlAlchemyDownloadRepository(
        async_sessionmaker(postgres_engine, expire_on_commit=False)
    )
    store = repository
    inspection_id, format_id = uuid4(), uuid4()
    owner = "a" * 64
    expires = NOW + timedelta(hours=1)

    saved = await store.save_inspection(
        ApplicationInspectionCreate(
            id=inspection_id,
            owner_hash=owner,
            idempotency_key="inspect-1",
            request_fingerprint="f" * 64,
            url_ciphertext=b"encrypted",
            url_nonce=b"n" * 16,
            url_key_id="fernet",
            extractor_key="Example",
            provider_media_id="media-1",
            title="Controlled sample",
            duration_seconds=10,
            metadata={"thumbnail_url": "data:image/avif;base64,Y292ZXI="},
            expires_at=expires,
            formats=(
                ApplicationFormatCreate(
                    id=format_id,
                    display_name="720p MP4",
                    plan_fingerprint="p" * 64,
                    semantic_plan={"height": 720},
                    provider_hints={"video_id": "video-id"},
                    expires_at=expires,
                ),
            ),
        )
    )
    loaded = await store.get_inspection(inspection_id, owner, NOW)
    await store.save_thumbnail(
        inspection_id,
        owner,
        ApplicationThumbnailObject(
            bucket="video-artifacts",
            object_key=f"thumbnails/{inspection_id}/cover.avif",
            content_type="image/avif",
            sha256="c" * 64,
            size_bytes=5,
        ),
    )
    thumbnail = await store.get_thumbnail_source(inspection_id, owner)
    job_id = uuid4()
    created = await store.create_job(
        ApplicationDownloadCreate(
            id=job_id,
            inspection_id=inspection_id,
            format_id=format_id,
            owner_hash=owner,
            idempotency_key="download-1",
            request_fingerprint="d" * 64,
            semantic_plan={"height": 720},
        ),
        now=NOW,
    )

    assert saved.created is True
    assert loaded.formats[0].display_name == "720p MP4"
    assert thumbnail.object is not None
    assert thumbnail.object.object_key.endswith("/cover.avif")
    assert thumbnail.legacy_data_url is None
    assert created.job.id == job_id
    assert (await store.get_job(job_id)).status == "queued"
    presentation = await store.get_download_presentation(job_id, owner)
    assert presentation.title == "Controlled sample"
    assert presentation.thumbnail_available is True
    history = await store.list_download_history(
        owner,
        page=1,
        page_size=20,
        status="queued",
        search="Controlled",
        now=NOW,
    )
    assert history.total == 1
    assert history.items[0].title == "Controlled sample"
    assert history.items[0].thumbnail_available is True
    assert history.summary.active == 1
    other_owner = await store.list_download_history(
        "b" * 64,
        page=1,
        page_size=20,
        status=None,
        search=None,
        now=NOW,
    )
    assert other_owner.total == 0

    claimed = await repository.claim_job(
        job_id,
        "worker-1",
        NOW,
        timedelta(minutes=1),
    )
    assert claimed is not None
    executed_context = ExecutionContext(
        provider_key="generic",
        registry_revision="registry-test",
        resolved_layer="L1",
        client="yt-dlp-default",
        engine_revision="engine",
        egress_route="default",
        egress_revision="egress-test",
        egress_class="unknown",
        egress_observed_ip=None,
        identity_used=False,
        identity_digest=None,
        browser_context_kind="none",
    )
    with pytest.raises(LeaseConflict):
        await repository.record_execution_context(
            job_id, "other-worker", claimed.attempt, executed_context, NOW
        )
    await repository.record_execution_context(
        job_id, "worker-1", claimed.attempt, executed_context, NOW
    )
    async with async_sessionmaker(postgres_engine, expire_on_commit=False)() as session:
        row = await session.get(DownloadJobRow, job_id)
        assert row is not None
        assert row.execution_context == executed_context.to_document()
        assert row.execution_context_attempt == claimed.attempt
    await repository.heartbeat(
        job_id,
        "worker-1",
        claimed.attempt,
        stage="uploading",
        stage_rank=5,
        progress=95,
        now=NOW + timedelta(seconds=1),
        lease_for=timedelta(minutes=1),
    )
    await repository.complete_success(
        job_id,
        "worker-1",
        claimed.attempt,
        ArtifactCreate(
            bucket="video-artifacts",
            sha256="0" * 64,
            size_bytes=1024,
            duration_ms=10_000,
            container="mp4",
            content_type="video/mp4",
            media_metadata={},
        ),
        now=NOW + timedelta(seconds=2),
    )
    artifact = await store.get_artifact(job_id, owner, NOW)

    assert artifact.object_key.endswith("/video.mp4")
    assert (await store.get_job(job_id)).status == "succeeded"
    async with async_sessionmaker(postgres_engine, expire_on_commit=False)() as session:
        inspection = await session.get(MediaInspectionRow, inspection_id)
        assert inspection is not None
        inspection.expires_at = NOW - timedelta(minutes=1)
        await session.commit()
    expired_source_history = await store.list_download_history(
        owner,
        page=1,
        page_size=20,
        status="succeeded",
        search="Controlled",
        now=NOW,
    )
    assert expired_source_history.items[0].title == "Controlled sample"
    assert expired_source_history.items[0].file_available is True
    expired_file_history = await store.list_download_history(
        owner,
        page=1,
        page_size=20,
        status="succeeded",
        search="Controlled",
        now=expires,
    )
    assert expired_file_history.items[0].file_available is True


@pytest.mark.asyncio
async def test_history_includes_browser_imports_and_searches_filename(
    postgres_engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    repository = SqlAlchemyDownloadRepository(sessions)
    store = repository
    job_id = uuid4()
    owner = "b" * 64
    async with sessions.begin() as session:
        session.add(
            DownloadJobRow(
                id=job_id,
                source_kind="browser_import",
                inspection_id=None,
                format_id=None,
                owner_hash=owner,
                idempotency_key="local-video-job",
                request_fingerprint="j" * 64,
                semantic_plan={"container": "mp4"},
                status="succeeded",
                progress=100,
                attempt=1,
                finished_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        session.add(
            MediaImportRow(
                id=job_id,
                owner_hash=owner,
                idempotency_key="local-video-import",
                request_fingerprint="k" * 64,
                source_format="mp4",
                display_name="我的样片.mp4",
                content_type="video/mp4",
                declared_size_bytes=2_048,
                declared_sha256="2" * 64,
                rights_statement_version="rights",
                status="ready",
                attempt=1,
                finished_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            ArtifactRow(
                id=uuid4(),
                job_id=job_id,
                attempt=1,
                bucket="video-artifacts",
                object_key=f"imports/{job_id}/video.mp4",
                sha256="2" * 64,
                size_bytes=2_048,
                duration_ms=8_000,
                container="mp4",
                content_type="video/mp4",
                media_metadata={},
                created_at=NOW,
            )
        )
        session.add(
            DownloadThumbnailRow(
                job_id=job_id,
                bucket="video-artifacts",
                object_key=f"thumbnails/{job_id}/first-frame.jpg",
                content_type="image/jpeg",
                sha256="3" * 64,
                size_bytes=512,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    history = await store.list_download_history(
        owner,
        page=1,
        page_size=20,
        status="succeeded",
        search="样片",
        now=NOW,
    )

    assert history.total == 1
    assert history.summary.succeeded == 1
    item = history.items[0]
    assert item.id == job_id
    assert item.inspection_id is None
    assert item.title == "我的样片.mp4"
    assert item.format_name == "MP4"
    assert item.thumbnail_available is True
    assert item.job_thumbnail_available is True
    assert item.file_available is True
    assert item.source_kind == "browser_import"

    view = await ApplicationGetDownloadHistory(store, now=lambda: NOW)(owner)
    assert view.items[0].thumbnail_url == f"/api/downloads/{job_id}/thumbnail"


@pytest.mark.asyncio
async def test_download_repository_prepares_and_finishes_owned_file_deletion(
    postgres_engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    repository = SqlAlchemyDownloadRepository(sessions)
    store = repository
    job_id = uuid4()
    owner = "d" * 64
    source_key = f"quarantine/video/{job_id}/1/source"
    artifact_key = f"downloads/{job_id}/1/video.mp4"
    thumbnail_key = f"thumbnails/{job_id}/{'e' * 64}.jpg"
    async with sessions.begin() as session:
        session.add(
            DownloadJobRow(
                id=job_id,
                source_kind="browser_import",
                owner_hash=owner,
                idempotency_key="delete-job",
                request_fingerprint="a" * 64,
                semantic_plan={"container": "mp4"},
                status="succeeded",
                progress=100,
                attempt=1,
                max_attempts=1,
                finished_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        session.add_all(
            (
                MediaImportRow(
                    id=job_id,
                    owner_hash=owner,
                    idempotency_key="delete-import",
                    request_fingerprint="b" * 64,
                    source_format="mp4",
                    display_name="待删除.mp4",
                    content_type="video/mp4",
                    declared_size_bytes=1_024,
                    declared_sha256="c" * 64,
                    rights_statement_version="rights",
                    status="ready",
                    attempt=1,
                    finished_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                ArtifactRow(
                    id=uuid4(),
                    job_id=job_id,
                    attempt=1,
                    bucket="video-artifacts",
                    object_key=artifact_key,
                    sha256="c" * 64,
                    size_bytes=1_024,
                    duration_ms=1_000,
                    container="mp4",
                    content_type="video/mp4",
                    media_metadata={},
                    created_at=NOW,
                ),
                DownloadThumbnailRow(
                    job_id=job_id,
                    bucket="video-artifacts",
                    object_key=thumbnail_key,
                    content_type="image/jpeg",
                    sha256="e" * 64,
                    size_bytes=128,
                    created_at=NOW,
                    updated_at=NOW,
                ),
            )
        )
        await session.flush()
        session.add(
            MediaImportAttemptRow(
                resource_id=job_id,
                attempt=1,
                status="ready",
                object_key=source_key,
                upload_id="upload-1",
                content_type="video/mp4",
                declared_size_bytes=1_024,
                actual_size_bytes=1_024,
                part_size_bytes=5 * 1024**2,
                part_count=1,
                expires_at=NOW + timedelta(hours=1),
                completed_at=NOW,
                finished_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    plan = await store.prepare_download_deletion(job_id, owner, now=NOW)

    assert {(item.object_key, item.upload_id) for item in plan.cleanup} == {
        (source_key, "upload-1"),
        (artifact_key, None),
        (thumbnail_key, None),
    }
    async with sessions() as session:
        artifact = await session.scalar(
            select(ArtifactRow).where(ArtifactRow.job_id == job_id)
        )
        assert artifact is not None
        assert artifact.deleted_at == NOW

    await store.finish_download_deletion(job_id, owner)

    async with sessions() as session:
        assert await session.get(DownloadJobRow, job_id) is None


@pytest.mark.asyncio
async def test_download_repository_handles_cancellation(
    postgres_engine: AsyncEngine,
) -> None:
    repository = SqlAlchemyDownloadRepository(
        async_sessionmaker(postgres_engine, expire_on_commit=False)
    )
    store = repository
    inspection_id, format_id, job_id = uuid4(), uuid4(), uuid4()
    owner = "b" * 64
    expires = NOW + timedelta(hours=1)
    await store.save_inspection(
        ApplicationInspectionCreate(
            id=inspection_id,
            owner_hash=owner,
            idempotency_key="inspect-cancel",
            request_fingerprint="i" * 64,
            url_ciphertext=b"encrypted",
            url_nonce=b"n" * 16,
            url_key_id="fernet",
            extractor_key="Example",
            provider_media_id="media-2",
            title="Controlled sample",
            duration_seconds=10,
            metadata={},
            expires_at=expires,
            formats=(
                ApplicationFormatCreate(
                    id=format_id,
                    display_name="720p MP4",
                    plan_fingerprint="p" * 64,
                    semantic_plan={"height": 720},
                    provider_hints={},
                    expires_at=expires,
                ),
            ),
        )
    )
    await store.create_job(
        ApplicationDownloadCreate(
            id=job_id,
            inspection_id=inspection_id,
            format_id=format_id,
            owner_hash=owner,
            idempotency_key="download-cancel",
            request_fingerprint="d" * 64,
            semantic_plan={"height": 720},
        ),
        now=NOW,
    )

    cancelled = await store.cancel_job(job_id, owner, NOW)

    assert cancelled.status == "cancelled"


@pytest.mark.asyncio
async def test_get_inspection_filters_expired_formats(
    postgres_engine: AsyncEngine,
) -> None:
    repository = SqlAlchemyDownloadRepository(
        async_sessionmaker(postgres_engine, expire_on_commit=False)
    )
    store = repository
    inspection_id, fresh_format_id, stale_format_id = uuid4(), uuid4(), uuid4()
    owner = "a" * 64
    fresh_expires = NOW + timedelta(hours=1)

    await store.save_inspection(
        ApplicationInspectionCreate(
            id=inspection_id,
            owner_hash=owner,
            idempotency_key="inspect-expiry",
            request_fingerprint="f" * 64,
            url_ciphertext=b"encrypted",
            url_nonce=b"n" * 16,
            url_key_id="fernet",
            extractor_key="Example",
            provider_media_id="media-1",
            title="Controlled sample",
            duration_seconds=10,
            metadata={"thumbnail_url": "data:image/avif;base64,Y292ZXI="},
            expires_at=fresh_expires,
            formats=(
                ApplicationFormatCreate(
                    id=fresh_format_id,
                    display_name="720p MP4",
                    plan_fingerprint="p" * 64,
                    semantic_plan={"height": 720},
                    provider_hints={"video_id": "video-id"},
                    expires_at=fresh_expires,
                ),
                ApplicationFormatCreate(
                    id=stale_format_id,
                    display_name="过期格式",
                    plan_fingerprint="s" * 64,
                    semantic_plan={"height": 360},
                    provider_hints={"video_id": "v2"},
                    expires_at=NOW - timedelta(minutes=1),
                ),
            ),
        )
    )

    loaded = await store.get_inspection(inspection_id, owner, NOW)

    assert [f.display_name for f in loaded.formats] == ["720p MP4"]
