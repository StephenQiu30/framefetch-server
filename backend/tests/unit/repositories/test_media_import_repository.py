from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from app.models import (
    ArtifactRow,
    DownloadJobRow,
    MediaImportAttemptRow,
    MediaImportRow,
    OutboxEventRow,
)
from app.repositories.downloads.repository import SqlAlchemyDownloadRepository
from app.repositories.imports.repository import SqlAlchemyMediaImportRepository
from app.services.import_execution.models import VerifiedImportArtifact
from app.services.imports.errors import (
    ImportPersistenceConflict,
    ImportPersistenceIdempotencyConflict,
)
from app.services.imports.events import CONTENT_IMPORT_VERIFY_REQUESTED
from app.services.imports.models import (
    ImportCleanupRef,
    ImportResourceCreate,
    ImportResourceSnapshot,
)
from app.services.imports.rules.enums import (
    ContentKind,
    ImportErrorCode,
    ImportSourceFormat,
    ImportStatus,
)
from app.services.imports.rules.keys import quarantine_object_key
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

NOW = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
RESOURCE_ID = UUID("11111111-1111-4111-8111-111111111111")
SECOND_ID = UUID("22222222-2222-4222-8222-222222222222")
OWNER_HASH = "a" * 64
FIVE_MIB = 5 * 1024**2
DECLARED_SIZE = FIVE_MIB + 1


@pytest.fixture
async def repositories(
    postgres_engine: AsyncEngine,
) -> tuple[
    SqlAlchemyMediaImportRepository,
    SqlAlchemyDownloadRepository,
    async_sessionmaker,
]:
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    yield (
        SqlAlchemyMediaImportRepository(sessions),
        SqlAlchemyDownloadRepository(sessions),
        sessions,
    )


def command(
    *,
    resource_id: UUID = RESOURCE_ID,
    fingerprint: str = "b" * 64,
    idempotency_key: str = "upload-1",
    remove_watermark: bool = False,
) -> ImportResourceCreate:
    return ImportResourceCreate(
        id=resource_id,
        owner_hash=OWNER_HASH,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        content_kind=ContentKind.VIDEO,
        source_format=ImportSourceFormat.MP4,
        display_name="example.mp4",
        content_type="video/mp4",
        declared_size_bytes=DECLARED_SIZE,
        declared_sha256="c" * 64,
        rights_statement_version="content-rights",
        remove_watermark=remove_watermark,
    )


async def test_create_is_idempotent_and_creates_browser_download_projection(
    repositories: tuple[
        SqlAlchemyMediaImportRepository,
        SqlAlchemyDownloadRepository,
        async_sessionmaker,
    ],
) -> None:
    repository, _, sessions = repositories

    created = await repository.create_resource(command(), now=NOW)
    replay = await repository.create_resource(
        command(resource_id=SECOND_ID), now=NOW + timedelta(seconds=1)
    )

    assert created.created is True
    assert replay.created is False
    assert replay.resource.id == RESOURCE_ID
    assert replay.resource.status == ImportStatus.UPLOADING.value
    async with sessions() as session:
        job = await session.get(DownloadJobRow, RESOURCE_ID)
        stored = await session.get(MediaImportRow, RESOURCE_ID)
        outbox_count = await session.scalar(select(func.count(OutboxEventRow.id)))
    assert job is not None
    assert job.source_kind == "browser_import"
    assert job.inspection_id is None
    assert job.format_id is None
    assert job.status == "running"
    assert job.stage == "downloading"
    assert stored is not None
    assert stored.rights_statement_version == "content-rights"
    # ORM metadata intentionally excludes deployment triggers. Creation must
    # not enqueue the remote downloader's download.requested event.
    assert outbox_count == 0


async def test_create_rejects_idempotency_fingerprint_mismatch(
    repositories: tuple[
        SqlAlchemyMediaImportRepository,
        SqlAlchemyDownloadRepository,
        async_sessionmaker,
    ],
) -> None:
    repository, _, _ = repositories
    await repository.create_resource(command(), now=NOW)

    with pytest.raises(ImportPersistenceIdempotencyConflict):
        await repository.create_resource(
            command(resource_id=SECOND_ID, fingerprint="d" * 64),
            now=NOW,
        )


async def test_complete_atomically_marks_verifying_and_writes_one_outbox_event(
    repositories: tuple[
        SqlAlchemyMediaImportRepository,
        SqlAlchemyDownloadRepository,
        async_sessionmaker,
    ],
) -> None:
    repository, _, sessions = repositories
    await repository.create_resource(command(), now=NOW)
    begun = await repository.begin_upload_attempt(
        RESOURCE_ID,
        OWNER_HASH,
        ContentKind.VIDEO,
        part_size_bytes=FIVE_MIB,
        part_count=2,
        expires_at=NOW + timedelta(minutes=15),
        now=NOW,
    )
    await repository.activate_upload_attempt(
        RESOURCE_ID,
        OWNER_HASH,
        ContentKind.VIDEO,
        begun.attempt.attempt,
        upload_id="multipart-1",
        now=NOW,
    )

    verifying = await repository.mark_verifying(
        RESOURCE_ID,
        OWNER_HASH,
        ContentKind.VIDEO,
        1,
        actual_size_bytes=DECLARED_SIZE,
        now=NOW + timedelta(seconds=1),
    )
    replay = await repository.mark_verifying(
        RESOURCE_ID,
        OWNER_HASH,
        ContentKind.VIDEO,
        1,
        actual_size_bytes=DECLARED_SIZE,
        now=NOW + timedelta(seconds=2),
    )

    assert verifying.status == ImportStatus.VERIFYING.value
    assert replay.version == verifying.version
    assert verifying.active_attempt is not None
    assert verifying.active_attempt.status == ImportStatus.VERIFYING.value
    async with sessions() as session:
        events = tuple((await session.scalars(select(OutboxEventRow))).all())
        job = await session.get(DownloadJobRow, RESOURCE_ID)
    assert len(events) == 1
    assert events[0].event_type == CONTENT_IMPORT_VERIFY_REQUESTED
    assert events[0].aggregate_type == "media_import"
    assert events[0].payload == {
        "resource_id": str(RESOURCE_ID),
        "content_kind": "video",
        "attempt": 1,
        "version": verifying.version,
    }
    assert job is not None
    assert (job.status, job.stage, job.stage_rank) == ("running", "verifying", 4)


async def test_refresh_supersedes_only_current_attempt_with_cleanup_reference(
    repositories: tuple[
        SqlAlchemyMediaImportRepository,
        SqlAlchemyDownloadRepository,
        async_sessionmaker,
    ],
) -> None:
    repository, _, sessions = repositories
    await repository.create_resource(command(), now=NOW)
    first = await repository.begin_upload_attempt(
        RESOURCE_ID,
        OWNER_HASH,
        ContentKind.VIDEO,
        part_size_bytes=FIVE_MIB,
        part_count=2,
        expires_at=NOW + timedelta(minutes=15),
        now=NOW,
    )
    await repository.activate_upload_attempt(
        RESOURCE_ID,
        OWNER_HASH,
        ContentKind.VIDEO,
        1,
        upload_id="multipart-1",
        now=NOW,
    )

    second = await repository.begin_upload_attempt(
        RESOURCE_ID,
        OWNER_HASH,
        ContentKind.VIDEO,
        part_size_bytes=FIVE_MIB,
        part_count=2,
        expires_at=NOW + timedelta(minutes=16),
        now=NOW + timedelta(minutes=1),
    )

    assert second.attempt.attempt == 2
    assert second.attempt.object_key == quarantine_object_key(
        ContentKind.VIDEO, RESOURCE_ID, 2
    )
    assert second.superseded == (
        # The storage cleanup happens only after this database transaction.
        ImportCleanupRef(first.attempt.object_key, "multipart-1"),
    )
    async with sessions() as session:
        stale = await session.get(MediaImportAttemptRow, (RESOURCE_ID, 1))
    assert stale is not None
    assert stale.status == ImportStatus.EXPIRED.value


async def test_retryable_failure_keeps_resource_uploadable_and_cancel_retries_cleanup(
    repositories: tuple[
        SqlAlchemyMediaImportRepository,
        SqlAlchemyDownloadRepository,
        async_sessionmaker,
    ],
) -> None:
    repository, _, _ = repositories
    await repository.create_resource(command(), now=NOW)
    await repository.begin_upload_attempt(
        RESOURCE_ID,
        OWNER_HASH,
        ContentKind.VIDEO,
        part_size_bytes=FIVE_MIB,
        part_count=2,
        expires_at=NOW + timedelta(minutes=15),
        now=NOW,
    )
    await repository.activate_upload_attempt(
        RESOURCE_ID,
        OWNER_HASH,
        ContentKind.VIDEO,
        1,
        upload_id="multipart-1",
        now=NOW,
    )

    failed = await repository.fail_attempt(
        RESOURCE_ID,
        OWNER_HASH,
        ContentKind.VIDEO,
        1,
        error_code=ImportErrorCode.STORAGE_UNAVAILABLE,
        now=NOW + timedelta(seconds=1),
    )
    assert failed.status == ImportStatus.UPLOADING.value
    assert failed.active_attempt is None

    refreshed = await repository.begin_upload_attempt(
        RESOURCE_ID,
        OWNER_HASH,
        ContentKind.VIDEO,
        part_size_bytes=FIVE_MIB,
        part_count=2,
        expires_at=NOW + timedelta(minutes=16),
        now=NOW + timedelta(minutes=1),
    )
    await repository.activate_upload_attempt(
        RESOURCE_ID,
        OWNER_HASH,
        ContentKind.VIDEO,
        refreshed.attempt.attempt,
        upload_id="multipart-2",
        now=NOW + timedelta(minutes=1),
    )
    cancelled = await repository.cancel_resource(
        RESOURCE_ID,
        OWNER_HASH,
        ContentKind.VIDEO,
        now=NOW + timedelta(minutes=2),
    )
    replay = await repository.cancel_resource(
        RESOURCE_ID,
        OWNER_HASH,
        ContentKind.VIDEO,
        now=NOW + timedelta(minutes=3),
    )

    assert cancelled.resource.status == ImportStatus.CANCELLED.value
    assert cancelled.resource.error_code is None
    assert cancelled.cleanup[0].upload_id == "multipart-2"
    assert replay.cleanup == cancelled.cleanup


async def test_remote_download_claim_and_recovery_ignore_browser_import_jobs(
    repositories: tuple[
        SqlAlchemyMediaImportRepository,
        SqlAlchemyDownloadRepository,
        async_sessionmaker,
    ],
) -> None:
    repository, downloads, sessions = repositories
    await repository.create_resource(command(), now=NOW)
    async with sessions() as session, session.begin():
        job = await session.get(DownloadJobRow, RESOURCE_ID)
        assert job is not None
        job.status = "queued"
        job.stage = None
        job.stage_rank = 0
        job.lease_expires_at = NOW - timedelta(minutes=1)

    claimed = await downloads.claim_job(
        RESOURCE_ID, "download-worker", NOW, timedelta(minutes=1)
    )
    recovered = await downloads.recover_stale_queued(NOW, NOW + timedelta(seconds=1))

    assert claimed is None
    assert recovered == ()


async def test_wrong_content_kind_and_owner_are_fail_closed(
    repositories: tuple[
        SqlAlchemyMediaImportRepository,
        SqlAlchemyDownloadRepository,
        async_sessionmaker,
    ],
) -> None:
    repository, _, _ = repositories
    await repository.create_resource(command(), now=NOW)

    assert (
        await repository.get_resource(RESOURCE_ID, OWNER_HASH, ContentKind.SCREENPLAY)
        is None
    )
    assert (
        await repository.get_resource(RESOURCE_ID, "e" * 64, ContentKind.VIDEO) is None
    )
    with pytest.raises(ImportPersistenceConflict):
        await repository.mark_verifying(
            RESOURCE_ID,
            OWNER_HASH,
            ContentKind.VIDEO,
            1,
            actual_size_bytes=DECLARED_SIZE,
            now=NOW,
        )


async def verifying_resource(
    repository: SqlAlchemyMediaImportRepository,
    *,
    remove_watermark: bool = False,
) -> ImportResourceSnapshot:
    await repository.create_resource(
        command(remove_watermark=remove_watermark), now=NOW
    )
    await repository.begin_upload_attempt(
        RESOURCE_ID,
        OWNER_HASH,
        ContentKind.VIDEO,
        part_size_bytes=FIVE_MIB,
        part_count=2,
        expires_at=NOW + timedelta(minutes=15),
        now=NOW,
    )
    await repository.activate_upload_attempt(
        RESOURCE_ID,
        OWNER_HASH,
        ContentKind.VIDEO,
        1,
        upload_id="multipart-1",
        now=NOW,
    )
    return await repository.mark_verifying(
        RESOURCE_ID,
        OWNER_HASH,
        ContentKind.VIDEO,
        1,
        actual_size_bytes=DECLARED_SIZE,
        now=NOW + timedelta(seconds=1),
    )


def verified_artifact() -> VerifiedImportArtifact:
    return VerifiedImportArtifact(
        sha256="d" * 64,
        size_bytes=DECLARED_SIZE,
        duration_ms=12_500,
        container="mp4",
        content_type="video/mp4",
        media_metadata={
            "video_streams": 1,
            "audio_streams": 0,
            "width": 1920,
            "height": 1080,
            "codecs": ["h264"],
        },
    )


@pytest.mark.parametrize("remove_watermark", [False, True])
async def test_worker_claim_heartbeat_and_completion_are_one_atomic_projection(
    repositories: tuple[
        SqlAlchemyMediaImportRepository,
        SqlAlchemyDownloadRepository,
        async_sessionmaker,
    ],
    remove_watermark: bool,
) -> None:
    repository, _, sessions = repositories
    verifying = await verifying_resource(repository, remove_watermark=remove_watermark)
    claim = await repository.claim_verification(
        RESOURCE_ID,
        ContentKind.VIDEO,
        1,
        verifying.version,
        worker_id="import-worker-a",
        now=NOW + timedelta(seconds=2),
        lease_for=timedelta(seconds=30),
    )

    assert claim is not None
    assert (
        await repository.claim_verification(
            RESOURCE_ID,
            ContentKind.VIDEO,
            1,
            claim.version,
            worker_id="import-worker-b",
            now=NOW + timedelta(seconds=3),
            lease_for=timedelta(seconds=30),
        )
        is None
    )
    assert await repository.heartbeat_verification(
        RESOURCE_ID,
        1,
        worker_id="import-worker-a",
        stage="uploading",
        progress=95,
        now=NOW + timedelta(seconds=4),
        lease_for=timedelta(seconds=30),
    )
    artifact = verified_artifact()
    await repository.complete_verification(
        claim,
        artifact,
        worker_id="import-worker-a",
        bucket="video-artifacts",
        now=NOW + timedelta(seconds=5),
    )
    # A broker redelivery after the commit sees the same deterministic artifact.
    await repository.complete_verification(
        claim,
        artifact,
        worker_id="import-worker-a",
        bucket="video-artifacts",
        now=NOW + timedelta(seconds=6),
    )

    async with sessions() as session:
        resource = await session.get(MediaImportRow, RESOURCE_ID)
        attempt = await session.get(MediaImportAttemptRow, (RESOURCE_ID, 1))
        job = await session.get(DownloadJobRow, RESOURCE_ID)
        stored = await session.scalar(
            select(ArtifactRow).where(ArtifactRow.job_id == RESOURCE_ID)
        )
    assert resource is not None and resource.status == ImportStatus.READY.value
    assert attempt is not None and attempt.status == ImportStatus.READY.value
    assert attempt.lease_owner is None and attempt.lease_expires_at is None
    assert job is not None
    assert (job.status, job.progress, job.attempt) == ("succeeded", 100, 1)
    assert stored is not None
    assert stored.object_key == f"downloads/{RESOURCE_ID}/1/video.mp4"
    assert stored.sha256 == artifact.sha256
    assert await repository.expected_artifact_object_keys() == frozenset(
        {stored.object_key}
    )

    from app.repositories.watermark import WatermarkRepository

    tasks = await WatermarkRepository(sessions).for_job(RESOURCE_ID, OWNER_HASH)
    assert len(tasks.items) == int(remove_watermark)
    if remove_watermark:
        assert tasks.items[0].status == "queued"


async def test_worker_validation_failure_is_terminal_and_clears_both_leases(
    repositories: tuple[
        SqlAlchemyMediaImportRepository,
        SqlAlchemyDownloadRepository,
        async_sessionmaker,
    ],
) -> None:
    repository, _, sessions = repositories
    verifying = await verifying_resource(repository)
    claim = await repository.claim_verification(
        RESOURCE_ID,
        ContentKind.VIDEO,
        1,
        verifying.version,
        worker_id="import-worker-a",
        now=NOW + timedelta(seconds=2),
        lease_for=timedelta(seconds=30),
    )
    assert claim is not None

    await repository.fail_verification(
        claim,
        ImportErrorCode.SHA256_MISMATCH,
        worker_id="import-worker-a",
        now=NOW + timedelta(seconds=3),
    )

    async with sessions() as session:
        resource = await session.get(MediaImportRow, RESOURCE_ID)
        attempt = await session.get(MediaImportAttemptRow, (RESOURCE_ID, 1))
        job = await session.get(DownloadJobRow, RESOURCE_ID)
    assert resource is not None
    assert (resource.status, resource.error_code) == (
        ImportStatus.FAILED.value,
        ImportErrorCode.SHA256_MISMATCH.value,
    )
    assert attempt is not None and attempt.lease_owner is None
    assert job is not None
    assert (job.status, job.error_code, job.lease_owner) == (
        "failed",
        "media_validation_failed",
        None,
    )


async def test_expired_worker_lease_is_requeued_once_and_can_be_reclaimed(
    repositories: tuple[
        SqlAlchemyMediaImportRepository,
        SqlAlchemyDownloadRepository,
        async_sessionmaker,
    ],
) -> None:
    repository, _, sessions = repositories
    verifying = await verifying_resource(repository)
    claim = await repository.claim_verification(
        RESOURCE_ID,
        ContentKind.VIDEO,
        1,
        verifying.version,
        worker_id="import-worker-a",
        now=NOW + timedelta(seconds=2),
        lease_for=timedelta(seconds=30),
    )
    assert claim is not None

    recovered = await repository.recover_expired_verifications(
        NOW + timedelta(seconds=33), limit=10
    )
    duplicate_sweep = await repository.recover_expired_verifications(
        NOW + timedelta(seconds=34), limit=10
    )
    reclaimed = await repository.claim_verification(
        RESOURCE_ID,
        ContentKind.VIDEO,
        1,
        claim.version,
        worker_id="import-worker-b",
        now=NOW + timedelta(seconds=35),
        lease_for=timedelta(seconds=30),
    )

    assert recovered == (RESOURCE_ID,)
    assert duplicate_sweep == ()
    assert reclaimed is not None
    async with sessions() as session:
        events = tuple((await session.scalars(select(OutboxEventRow))).all())
    assert len(events) == 2
    assert events[-1].payload == {
        "resource_id": str(RESOURCE_ID),
        "content_kind": "video",
        "attempt": 1,
        "version": claim.version,
    }
