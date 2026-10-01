from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.repositories.contracts import ArtifactCreate
from app.repositories.downloads.repository import SqlAlchemyDownloadRepository
from app.repositories.errors import IdempotencyConflict, RepositoryNotFound
from app.services.downloads.download_models import DownloadCreate
from app.services.downloads.inspection_models import FormatCreate, InspectionCreate
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker


@pytest.fixture
async def repository(postgres_engine: AsyncEngine) -> SqlAlchemyDownloadRepository:
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    yield SqlAlchemyDownloadRepository(factory)


async def _inspection(repository: SqlAlchemyDownloadRepository) -> tuple:
    now = datetime.now(UTC)
    inspection_id = uuid4()
    format_id = uuid4()
    await repository.save_inspection(
        InspectionCreate(
            id=inspection_id,
            owner_hash="a" * 64,
            idempotency_key="inspect-1",
            request_fingerprint="e" * 64,
            url_ciphertext=b"ciphertext",
            url_nonce=b"nonce",
            url_key_id="primary",
            extractor_key="Youtube",
            provider_media_id="controlled-video",
            title="Controlled video",
            duration_seconds=30,
            metadata={
                "thumbnail": None,
                "execution_context": {
                    "provider_key": "youtube",
                    "resolved_layer": "L1",
                    "egress_route": "default",
                    "client": "yt-dlp-default",
                    "registry_revision": "registry-test",
                    "egress_revision": "egress-test",
                    "egress_class": "unknown",
                    "egress_observed_ip": None,
                    "identity_digest": None,
                    "browser_context_kind": "none",
                    "identity_used": False,
                    "engine_revision": "5d6b8c8",
                },
            },
            expires_at=now + timedelta(minutes=15),
            formats=(
                FormatCreate(
                    id=format_id,
                    display_name="1080p MP4",
                    plan_fingerprint="b" * 64,
                    semantic_plan={"height": 1080, "container_preference": "mp4"},
                    provider_hints={"video": "137", "audio": "140"},
                    expires_at=now + timedelta(minutes=15),
                ),
            ),
        )
    )
    return inspection_id, format_id, now


@pytest.mark.asyncio
async def test_job_outbox_lease_progress_and_success_are_atomic(repository) -> None:
    inspection_id, format_id, now = await _inspection(repository)
    command = DownloadCreate(
        id=uuid4(),
        inspection_id=inspection_id,
        format_id=format_id,
        owner_hash="a" * 64,
        idempotency_key="download-1",
        request_fingerprint="c" * 64,
        semantic_plan={"height": 1080, "container_preference": "mp4"},
        max_attempts=3,
    )

    created = await repository.create_job(command, now=now)
    duplicate = await repository.create_job(command, now=now)
    equivalent = await repository.create_job(
        replace(
            command,
            id=uuid4(),
            idempotency_key="download-equivalent",
        ),
        now=now,
    )
    assert created.created is True
    assert created.job.source_kind == "remote_provider"
    assert duplicate.created is False
    assert duplicate.job.id == created.job.id
    assert equivalent.created is False
    assert equivalent.job.id == created.job.id

    claimed = await repository.claim_job(
        command.id, "worker-1", now, timedelta(minutes=30)
    )
    assert claimed is not None
    assert (claimed.status, claimed.stage, claimed.attempt) == (
        "running",
        "revalidating",
        1,
    )
    source = await repository.get_job_source(
        command.id, "worker-1", 1, now + timedelta(seconds=1)
    )
    assert source.url_ciphertext == b"ciphertext"
    assert source.semantic_plan["height"] == 1080
    assert source.provider_hints["video"] == "137"
    assert source.execution_context["provider_key"] == "youtube"
    late_source = await repository.get_job_source(
        command.id, "worker-1", 1, now + timedelta(minutes=16)
    )
    assert late_source.inspection_id == inspection_id
    with pytest.raises(RepositoryNotFound):
        await repository.get_job_source(uuid4(), "worker-1", 1, now)

    assert await repository.heartbeat(
        command.id,
        "worker-1",
        1,
        stage="downloading",
        stage_rank=2,
        progress=35,
        now=now + timedelta(seconds=5),
        lease_for=timedelta(seconds=60),
    )
    assert await repository.heartbeat(
        command.id,
        "worker-1",
        1,
        stage="revalidating",
        stage_rank=1,
        progress=10,
        now=now + timedelta(seconds=6),
        lease_for=timedelta(seconds=60),
    )
    current = await repository.get_job(command.id)
    assert (current.stage, current.progress) == ("downloading", 35)
    assert await repository.heartbeat(
        command.id,
        "worker-1",
        1,
        stage="uploading",
        stage_rank=5,
        progress=95,
        now=now + timedelta(seconds=7),
        lease_for=timedelta(seconds=60),
    )

    artifact = await repository.complete_success(
        command.id,
        "worker-1",
        1,
        ArtifactCreate(
            bucket="video-artifacts",
            sha256="d" * 64,
            size_bytes=1024,
            duration_ms=30_000,
            container="mp4",
            content_type="video/mp4",
            media_metadata={"video_streams": 1, "audio_streams": 1},
        ),
        now=now + timedelta(seconds=10),
    )
    assert artifact.object_key == f"downloads/{command.id}/1/video.mp4"
    assert (await repository.get_job(command.id)).status == "succeeded"
    fetched = await repository.get_artifact(
        command.id, "a" * 64, now + timedelta(seconds=11)
    )
    assert fetched.sha256 == "d" * 64


@pytest.mark.asyncio
async def test_retry_can_enqueue_after_inspection_expiry(repository) -> None:
    inspection_id, format_id, now = await _inspection(repository)
    original = DownloadCreate(
        id=uuid4(),
        inspection_id=inspection_id,
        format_id=format_id,
        owner_hash="a" * 64,
        idempotency_key="download-original",
        request_fingerprint="1" * 64,
        semantic_plan={"height": 1080, "container_preference": "mp4"},
    )
    await repository.create_job(original, now=now)
    retry = replace(
        original,
        id=uuid4(),
        idempotency_key="download-retry",
        request_fingerprint="2" * 64,
        allow_expired_source=True,
    )

    created = await repository.create_job(
        retry,
        now=now + timedelta(minutes=16),
    )

    assert created.created is True
    assert created.job.id == retry.id


@pytest.mark.asyncio
async def test_same_idempotency_key_rejects_a_different_request(repository) -> None:
    inspection_id, format_id, now = await _inspection(repository)
    first = DownloadCreate(
        id=uuid4(),
        inspection_id=inspection_id,
        format_id=format_id,
        owner_hash="a" * 64,
        idempotency_key="same",
        request_fingerprint="1" * 64,
        semantic_plan={"height": 1080, "container_preference": "mp4"},
    )
    second = DownloadCreate(
        id=uuid4(),
        inspection_id=inspection_id,
        format_id=format_id,
        owner_hash="a" * 64,
        idempotency_key="same",
        request_fingerprint="2" * 64,
        semantic_plan={"height": 720},
    )
    await repository.create_job(first, now=now)
    with pytest.raises(IdempotencyConflict):
        await repository.create_job(second, now=now)
