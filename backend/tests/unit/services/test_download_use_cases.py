from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.services.downloads.create_download import CreateDownload
from app.services.downloads.delete_download import DeleteDownload
from app.services.downloads.download_models import (
    ArtifactSnapshot,
    DownloadCleanupRef,
    JobSnapshot,
)
from app.services.downloads.errors import ApplicationError, ApplicationErrorCode
from app.services.downloads.fingerprints import HmacRequestFingerprinter
from app.services.downloads.inspection_models import FormatSnapshot, InspectionSnapshot
from app.services.downloads.plans import plan_to_documents
from app.services.downloads.queries import CancelDownload, GetDownload, IssueDownloadUrl
from app.services.downloads.retry_download import RetryDownload
from app.services.downloads.rules.enums import (
    DownloadErrorCode,
    DownloadSourceKind,
    DownloadStage,
    DownloadStatus,
    MediaKind,
)
from tests.unit.services.fakes import FakeRepository, FakeStorage
from tests.unit.services.test_inspect_media import (
    NOW,
    OWNER,
    plan,
)


@pytest.mark.parametrize(
    "stored_code", ["removed_provider_code", "unknown_future_code"]
)
async def test_historical_unknown_download_error_remains_readable(stored_code) -> None:
    repository = FakeRepository()
    inspection_id, format_id = seed_inspection(repository)
    job = await creator(repository)(inspection_id, format_id, OWNER, "historic-error")
    repository.jobs[job.id] = replace(
        repository.jobs[job.id], status="failed", error_code=stored_code, attempt=1
    )

    result = await GetDownload(repository, now=lambda: NOW)(job.id, OWNER)

    assert result.status is DownloadStatus.FAILED
    assert result.error_code is DownloadErrorCode.INTERNAL_ERROR


async def test_context_changed_download_requires_new_resolution_before_retry() -> None:
    repository = FakeRepository()
    inspection_id, format_id = seed_inspection(repository)
    original = await creator(repository)(inspection_id, format_id, OWNER, "old-context")
    repository.jobs[original.id] = replace(
        repository.jobs[original.id],
        status="failed",
        error_code=DownloadErrorCode.CONTEXT_CHANGED.value,
        attempt=1,
        finished_at=NOW,
    )

    with pytest.raises(ApplicationError) as changed:
        await retrier(repository)(original.id, OWNER, "retry-old-context")

    assert changed.value.code is ApplicationErrorCode.CONTEXT_CHANGED
    assert len(repository.jobs) == 1
    assert repository.outbox_events == 1


def seed_inspection(
    repository: FakeRepository,
    *,
    owner: str = OWNER,
    expires_at: datetime | None = None,
) -> tuple[UUID, UUID]:
    inspection_id, format_id = uuid4(), uuid4()
    semantic, hints = plan_to_documents(plan())
    repository.inspections[inspection_id] = InspectionSnapshot(
        id=inspection_id,
        owner_hash=owner,
        request_fingerprint="a" * 64,
        extractor_key="Controlled",
        provider_media_id="video-1",
        title="Owned video",
        duration_seconds=30,
        metadata={"thumbnail_url": "data:image/avif;base64,Y292ZXI="},
        expires_at=expires_at or NOW + timedelta(minutes=15),
        formats=(
            FormatSnapshot(
                id=format_id,
                display_name="1080p MP4",
                plan_fingerprint="b" * 64,
                semantic_plan=semantic,
                provider_hints=hints,
                expires_at=expires_at or NOW + timedelta(minutes=15),
            ),
        ),
    )
    return inspection_id, format_id


def seed_video_collection(repository: FakeRepository) -> tuple[UUID, UUID]:
    inspection_id, format_id = uuid4(), uuid4()
    expires_at = NOW + timedelta(minutes=15)
    semantic = {
        "media_kind": MediaKind.VIDEO_COLLECTION.value,
        "asset_count": 2,
    }
    repository.inspections[inspection_id] = InspectionSnapshot(
        id=inspection_id,
        owner_hash=OWNER,
        request_fingerprint="a" * 64,
        extractor_key="Instagram",
        provider_media_id="collection-1",
        title="视频合集",
        duration_seconds=0,
        metadata=semantic,
        expires_at=expires_at,
        formats=(
            FormatSnapshot(
                id=format_id,
                display_name="下载 2 个视频（ZIP）",
                plan_fingerprint="b" * 64,
                semantic_plan=semantic,
                provider_hints={},
                expires_at=expires_at,
            ),
        ),
    )
    return inspection_id, format_id


def creator(repository: FakeRepository) -> CreateDownload:
    return CreateDownload(
        repository=repository,
        fingerprinter=HmacRequestFingerprinter(b"k" * 32),
        now=lambda: NOW,
        new_id=uuid4,
    )


def retrier(repository: FakeRepository) -> RetryDownload:
    return RetryDownload(
        repository=repository,
        fingerprinter=HmacRequestFingerprinter(b"k" * 32),
        now=lambda: NOW,
        new_id=uuid4,
    )


@pytest.mark.asyncio
async def test_create_download_persists_job_and_outbox_idempotently() -> None:
    repository = FakeRepository()
    inspection_id, format_id = seed_inspection(repository)
    create = creator(repository)

    first = await create(inspection_id, format_id, OWNER, "download-1")
    replay = await create(inspection_id, format_id, OWNER, "download-1")

    assert first.id == replay.id
    assert first.status is DownloadStatus.QUEUED
    assert repository.outbox_events == 1
    command = repository.download_commands[0]
    assert command.max_attempts == 3
    assert command.semantic_plan["height"] == 1080
    assert "hints" not in command.semantic_plan


@pytest.mark.asyncio
async def test_create_download_persists_video_collection_without_a_video_plan() -> None:
    repository = FakeRepository()
    inspection_id, format_id = seed_video_collection(repository)

    created = await creator(repository)(
        inspection_id,
        format_id,
        OWNER,
        "video-collection-download",
    )

    assert created.media_kind is MediaKind.VIDEO_COLLECTION
    assert created.asset_count == 2
    assert repository.download_commands[0].semantic_plan == {
        "media_kind": MediaKind.VIDEO_COLLECTION.value,
        "asset_count": 2,
    }


@pytest.mark.asyncio
async def test_create_rejects_owner_mismatch_expiry_and_idempotency_conflict() -> None:
    repository = FakeRepository()
    foreign_id, foreign_format = seed_inspection(repository, owner="b" * 64)
    expired_id, expired_format = seed_inspection(
        repository, expires_at=NOW - timedelta(seconds=1)
    )
    create = creator(repository)

    with pytest.raises(ApplicationError) as foreign:
        await create(foreign_id, foreign_format, OWNER, "foreign")
    assert foreign.value.code is ApplicationErrorCode.NOT_FOUND

    with pytest.raises(ApplicationError) as expired:
        await create(expired_id, expired_format, OWNER, "expired")
    assert expired.value.code is ApplicationErrorCode.RESOURCE_EXPIRED

    format_expired_id, format_expired = seed_inspection(repository)
    source = repository.inspections[format_expired_id]
    repository.inspections[format_expired_id] = replace(
        source,
        formats=(replace(source.formats[0], expires_at=NOW),),
    )
    with pytest.raises(ApplicationError) as expired_selection:
        await create(format_expired_id, format_expired, OWNER, "format-expired")
    assert expired_selection.value.code is ApplicationErrorCode.RESOURCE_EXPIRED

    first_id, first_format = seed_inspection(repository)
    other_id, other_format = seed_inspection(repository)
    await create(first_id, first_format, OWNER, "same")
    with pytest.raises(ApplicationError) as conflict:
        await create(other_id, other_format, OWNER, "same")
    assert conflict.value.code is ApplicationErrorCode.IDEMPOTENCY_CONFLICT


@pytest.mark.asyncio
async def test_get_and_cancel_enforce_owner_and_status() -> None:
    repository = FakeRepository()
    inspection_id, format_id = seed_inspection(repository)
    created = await creator(repository)(inspection_id, format_id, OWNER, "download-1")

    with pytest.raises(ApplicationError) as foreign:
        await GetDownload(repository, now=lambda: NOW)(created.id, "b" * 64)
    assert foreign.value.code is ApplicationErrorCode.NOT_FOUND

    cancelled = await CancelDownload(repository, now=lambda: NOW)(created.id, OWNER)
    assert cancelled.status is DownloadStatus.CANCELLED
    with pytest.raises(ApplicationError) as terminal:
        await CancelDownload(repository, now=lambda: NOW)(created.id, OWNER)
    assert terminal.value.code is ApplicationErrorCode.INVALID_STATE


@pytest.mark.asyncio
async def test_delete_cancels_active_job_and_removes_owned_objects() -> None:
    repository, storage = FakeRepository(), FakeStorage()
    inspection_id, format_id = seed_inspection(repository)
    created = await creator(repository)(inspection_id, format_id, OWNER, "delete-1")
    source_key = f"quarantine/video/{created.id}/1/source"
    artifact_key = f"downloads/{created.id}/1/video.mp4"
    thumbnail_key = f"thumbnails/{created.id}/{'c' * 64}.jpg"
    repository.deletion_cleanup[created.id] = (
        DownloadCleanupRef(source_key, "upload-1"),
        DownloadCleanupRef(artifact_key),
        DownloadCleanupRef(thumbnail_key),
    )
    repository.jobs[created.id] = replace(
        repository.jobs[created.id], status="running", attempt=1
    )

    cancel = CancelDownload(repository, now=lambda: NOW)
    await DeleteDownload(repository, storage, cancel, now=lambda: NOW)(
        created.id, OWNER
    )

    assert created.id not in repository.jobs
    assert storage.aborted == [(source_key, "upload-1")]
    assert storage.deleted == [source_key, artifact_key, thumbnail_key]


@pytest.mark.asyncio
async def test_delete_hides_foreign_jobs_and_preserves_analysis_locked_job() -> None:
    repository, storage = FakeRepository(), FakeStorage()
    inspection_id, format_id = seed_inspection(repository)
    created = await creator(repository)(inspection_id, format_id, OWNER, "delete-2")
    repository.jobs[created.id] = replace(
        repository.jobs[created.id], status="succeeded", attempt=1
    )
    delete = DeleteDownload(
        repository,
        storage,
        CancelDownload(repository, now=lambda: NOW),
        now=lambda: NOW,
    )

    with pytest.raises(ApplicationError) as foreign:
        await delete(created.id, "b" * 64)
    assert foreign.value.code is ApplicationErrorCode.NOT_FOUND

    repository.deletion_conflict = True
    with pytest.raises(ApplicationError) as locked:
        await delete(created.id, OWNER)
    assert locked.value.code is ApplicationErrorCode.INVALID_STATE
    assert created.id in repository.jobs


@pytest.mark.asyncio
async def test_browser_import_details_and_cancel_use_import_aggregate() -> None:
    repository = FakeRepository()
    job_id = uuid4()
    repository.jobs[job_id] = JobSnapshot(
        id=job_id,
        inspection_id=None,
        format_id=None,
        owner_hash=OWNER,
        request_fingerprint="a" * 64,
        semantic_plan={"source_kind": "browser_import", "container": "mp4"},
        status="running",
        stage="downloading",
        progress=0,
        attempt=0,
        max_attempts=1,
        version=0,
        lease_owner=None,
        lease_expires_at=None,
        heartbeat_at=None,
        started_at=NOW,
        retry_at=None,
        finished_at=None,
        error_code=None,
        created_at=NOW,
        updated_at=NOW,
        source_kind=DownloadSourceKind.BROWSER_IMPORT.value,
    )

    class Canceller:
        def __init__(self) -> None:
            self.calls: list[tuple[UUID, str]] = []

        async def __call__(self, resource_id: UUID, owner_hash: str) -> object:
            self.calls.append((resource_id, owner_hash))
            current = repository.jobs[resource_id]
            repository.jobs[resource_id] = replace(
                current,
                status="cancelled",
                stage=None,
                finished_at=NOW,
                error_code="cancelled",
                version=current.version + 1,
            )
            return object()

    canceller = Canceller()
    details = await GetDownload(repository, now=lambda: NOW)(job_id, OWNER)
    cancelled = await CancelDownload(
        repository,
        now=lambda: NOW,
        browser_import_canceller=canceller,
    )(job_id, OWNER)

    assert details.source_kind is DownloadSourceKind.BROWSER_IMPORT
    assert details.source_label == "本地视频上传"
    assert details.stage is DownloadStage.DOWNLOADING
    assert cancelled.status is DownloadStatus.CANCELLED
    assert canceller.calls == [(job_id, OWNER)]


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_status", ["failed", "cancelled"])
async def test_retry_creates_a_new_job_and_preserves_terminal_history(
    terminal_status: str,
) -> None:
    repository = FakeRepository()
    inspection_id, format_id = seed_inspection(repository)
    original = await creator(repository)(inspection_id, format_id, OWNER, "original")
    repository.jobs[original.id] = replace(
        repository.jobs[original.id],
        status=terminal_status,
        attempt=3,
        finished_at=NOW,
    )

    retried = await retrier(repository)(original.id, OWNER, "manual-retry")
    replay = await retrier(repository)(original.id, OWNER, "manual-retry")

    assert retried.id != original.id
    assert replay.id == retried.id
    assert retried.status is DownloadStatus.QUEUED
    assert retried.attempt == 0
    assert repository.jobs[original.id].status == terminal_status
    assert repository.outbox_events == 2


@pytest.mark.asyncio
async def test_retry_rejects_active_successful_with_file_and_foreign_jobs() -> None:
    repository = FakeRepository()
    inspection_id, format_id = seed_inspection(repository)
    original = await creator(repository)(inspection_id, format_id, OWNER, "original")
    retry = retrier(repository)

    for status in ("queued", "running", "retry_wait"):
        repository.jobs[original.id] = replace(
            repository.jobs[original.id], status=status
        )
        with pytest.raises(ApplicationError) as invalid:
            await retry(original.id, OWNER, f"retry-{status}")
        assert invalid.value.code is ApplicationErrorCode.INVALID_STATE

    repository.jobs[original.id] = replace(
        repository.jobs[original.id], status="succeeded", progress=100
    )
    repository.artifacts[original.id] = ArtifactSnapshot(
        id=uuid4(),
        job_id=original.id,
        attempt=1,
        bucket="video-artifacts",
        object_key=f"downloads/{original.id}/1/video.mp4",
        sha256="d" * 64,
        size_bytes=1_024,
        duration_ms=30_000,
        container="mp4",
        content_type="video/mp4",
        media_metadata={},
    )
    with pytest.raises(ApplicationError) as available:
        await retry(original.id, OWNER, "retry-succeeded-available")
    assert available.value.code is ApplicationErrorCode.INVALID_STATE

    repository.jobs[original.id] = replace(
        repository.jobs[original.id], status="failed"
    )
    with pytest.raises(ApplicationError) as foreign:
        await retry(original.id, "b" * 64, "retry-foreign")
    assert foreign.value.code is ApplicationErrorCode.NOT_FOUND


@pytest.mark.asyncio
async def test_retry_queues_an_expired_source_and_preserves_semantic_plan() -> None:
    repository = FakeRepository()
    inspection_id, format_id = seed_inspection(repository)
    original = await creator(repository)(inspection_id, format_id, OWNER, "original")
    repository.jobs[original.id] = replace(
        repository.jobs[original.id], status="failed", finished_at=NOW
    )
    repository.inspections[inspection_id] = replace(
        repository.inspections[inspection_id], expires_at=NOW
    )

    retried = await retrier(repository)(original.id, OWNER, "retry-expired")

    assert retried.id != original.id
    command = repository.download_commands[-1]
    assert command.inspection_id == inspection_id
    assert command.format_id == format_id
    assert command.allow_expired_source is True
    assert command.semantic_plan == repository.jobs[original.id].semantic_plan


@pytest.mark.asyncio
async def test_retry_does_not_require_provider_validation_before_enqueue() -> None:
    repository = FakeRepository()
    inspection_id, format_id = seed_inspection(repository)
    original = await creator(repository)(inspection_id, format_id, OWNER, "original")
    repository.jobs[original.id] = replace(
        repository.jobs[original.id], status="failed", finished_at=NOW
    )

    retried = await retrier(repository)(original.id, OWNER, "retry-provider-down")

    assert retried.status is DownloadStatus.QUEUED
    assert len(repository.download_commands) == 2


@pytest.mark.asyncio
async def test_retry_allows_a_succeeded_job_after_its_file_is_cleaned() -> None:
    repository = FakeRepository()
    inspection_id, format_id = seed_inspection(repository)
    original = await creator(repository)(inspection_id, format_id, OWNER, "original")
    repository.jobs[original.id] = replace(
        repository.jobs[original.id], status="succeeded", progress=100
    )
    repository.artifacts.pop(original.id, None)

    retried = await retrier(repository)(original.id, OWNER, "retry-expired-file")

    assert retried.status is DownloadStatus.QUEUED


@pytest.mark.asyncio
async def test_download_url_requires_success_and_available_artifact() -> None:
    repository, storage = FakeRepository(), FakeStorage()
    inspection_id, format_id = seed_inspection(repository)
    created = await creator(repository)(inspection_id, format_id, OWNER, "download-1")
    issue = IssueDownloadUrl(
        repository, storage, now=lambda: NOW, url_ttl=timedelta(minutes=5)
    )

    with pytest.raises(ApplicationError) as pending:
        await issue(created.id, OWNER)
    assert pending.value.code is ApplicationErrorCode.DOWNLOAD_NOT_READY

    repository.jobs[created.id] = replace(
        repository.jobs[created.id], status="succeeded", progress=100
    )
    repository.artifacts[created.id] = ArtifactSnapshot(
        id=uuid4(),
        job_id=created.id,
        attempt=1,
        bucket="video-artifacts",
        object_key=f"downloads/{created.id}/1/video.mp4",
        sha256="d" * 64,
        size_bytes=1_024,
        duration_ms=30_000,
        container="mp4",
        content_type="video/mp4",
        media_metadata={},
    )
    details = await GetDownload(repository, now=lambda: NOW)(created.id, OWNER)
    assert details.file_available is True
    assert details.title == "Owned video"
    assert details.thumbnail_url == f"/api/inspections/{inspection_id}/thumbnail"
    assert details.format_plan is not None
    assert details.format_plan.height == 1080
    result = await issue(created.id, OWNER)

    assert result.url == "https://objects.example/download-token"
    assert result.expires_at == NOW + timedelta(minutes=5)
    assert result.filename == "Owned video.mp4"
    assert storage.calls == [
        (f"downloads/{created.id}/1/video.mp4", 300, "Owned video", False)
    ]

    persistent_details = await GetDownload(repository, now=lambda: NOW)(
        created.id, OWNER
    )
    assert persistent_details.file_available is True
    await issue(created.id, OWNER)


@pytest.mark.asyncio
async def test_download_url_passes_inspection_title_to_storage() -> None:
    repository, storage = FakeRepository(), FakeStorage()
    inspection_id, format_id = seed_inspection(repository)
    created = await creator(repository)(inspection_id, format_id, OWNER, "download-2")
    repository.jobs[created.id] = replace(
        repository.jobs[created.id], status="succeeded", progress=100
    )
    repository.artifacts[created.id] = ArtifactSnapshot(
        id=uuid4(),
        job_id=created.id,
        attempt=1,
        bucket="video-artifacts",
        object_key=f"downloads/{created.id}/1/video.mp4",
        sha256="d" * 64,
        size_bytes=1_024,
        duration_ms=30_000,
        container="mp4",
        content_type="video/mp4",
        media_metadata={},
    )
    issue = IssueDownloadUrl(
        repository, storage, now=lambda: NOW, url_ttl=timedelta(minutes=5)
    )

    await issue(created.id, OWNER)

    assert storage.calls[-1] == (
        f"downloads/{created.id}/1/video.mp4",
        300,
        "Owned video",
        False,
    )

    await issue(created.id, OWNER, preview=True)

    assert storage.calls[-1] == (
        f"downloads/{created.id}/1/video.mp4",
        300,
        "Owned video",
        True,
    )

    proxied = await issue(created.id, OWNER, use_browser_proxy=True)

    assert proxied.url == f"/api/downloads/{created.id}/file"
    assert proxied.filename == "Owned video.mp4"


@pytest.mark.asyncio
async def test_download_url_omits_missing_inspection_title() -> None:
    repository, storage = FakeRepository(), FakeStorage()
    inspection_id, format_id = seed_inspection(repository)
    created = await creator(repository)(inspection_id, format_id, OWNER, "download-3")
    repository.jobs[created.id] = replace(
        repository.jobs[created.id], status="succeeded", progress=100
    )
    repository.artifacts[created.id] = ArtifactSnapshot(
        id=uuid4(),
        job_id=created.id,
        attempt=1,
        bucket="video-artifacts",
        object_key=f"downloads/{created.id}/1/video.mp4",
        sha256="d" * 64,
        size_bytes=1_024,
        duration_ms=30_000,
        container="mp4",
        content_type="video/mp4",
        media_metadata={},
    )
    issue = IssueDownloadUrl(
        repository, storage, now=lambda: NOW, url_ttl=timedelta(minutes=5)
    )
    repository.inspections.pop(inspection_id)

    await issue(created.id, OWNER)

    assert storage.calls[-1] == (
        f"downloads/{created.id}/1/video.mp4",
        300,
        None,
        False,
    )
