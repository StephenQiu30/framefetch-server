from datetime import timedelta
from uuid import uuid4

import pytest
from app.core.db import create_session_factory, utc_now
from app.models import ArtifactRow, OutboxEventRow, WatermarkTaskRow
from app.repositories.downloads.delete_repository import DownloadDeleteRepository
from app.repositories.errors import RepositoryConflict
from app.repositories.watermark import WatermarkRepository
from app.services.downloads.errors import ApplicationError
from app.services.quotas import DEFAULT_USER_QUOTA
from sqlalchemy import select
from tests.unit.repositories.analysis.factories import seed_artifact


@pytest.fixture
async def setup(postgres_engine):
    sessions = create_session_factory(postgres_engine)
    source = await seed_artifact(sessions, utc_now())
    repo = WatermarkRepository(sessions)
    await repo.heartbeat_worker("worker")
    return sessions, source, repo


async def create(source, repo, key="key"):
    return await repo.create(
        source.download_id, source.owner_hash, key, DEFAULT_USER_QUOTA
    )


async def test_replay_owner_active_and_publication_fencing(setup):
    sessions, source, repo = setup
    task = await create(source, repo)
    assert (await create(source, repo)).id == task.id
    with pytest.raises(ApplicationError):
        await create(source, repo, "different")
    with pytest.raises(ApplicationError):
        await repo.for_job(source.download_id, "wrong")
    assert await repo.claim(task.id, "worker") is not None
    assert await repo.claim(task.id, "other") is None
    assert not await repo.finish(task.id, "other", 1, size=20, sha256="a" * 64)
    assert await repo.finish(task.id, "worker", 1, size=20, sha256="a" * 64)
    row, original = await repo.artifact(task.id, source.owner_hash)
    assert row.object_key != original.object_key
    assert original.sha256 == source.sha256
    await repo.offline("worker")
    assert (await create(source, repo)).id == task.id
    async with sessions() as session:
        assert len((await session.scalars(select(OutboxEventRow))).all()) == 1


async def test_cancel_kills_lease_prevents_publish_and_preserves_original(setup):
    sessions, source, repo = setup
    task = await create(source, repo)
    claimed = await repo.claim(task.id, "worker")
    await repo.cancel(task.id, source.owner_hash)
    assert not await repo.heartbeat_task(task.id, "worker", 1)
    assert not await repo.finish(task.id, "worker", 1, size=20, sha256="a" * 64)
    deletion = DownloadDeleteRepository(sessions)
    with pytest.raises(RepositoryConflict):
        await deletion.prepare_download_deletion(
            source.download_id, source.owner_hash, now=utc_now()
        )
    await repo.cleaned(claimed[0].object_key)
    await repo.release(task.id, "worker", 1)
    plan = await deletion.prepare_download_deletion(
        source.download_id, source.owner_hash, now=utc_now()
    )
    assert len(plan.cleanup) == 1
    await deletion.finish_download_deletion(source.download_id, source.owner_hash)
    async with sessions() as session:
        assert await session.get(WatermarkTaskRow, task.id) is None


async def test_expired_lease_recovery_keeps_queued_and_tracks_cleanup(setup):
    sessions, source, repo = setup
    task = await create(source, repo)
    async with sessions() as session, session.begin():
        row = await session.get(WatermarkTaskRow, task.id)
        row.updated_at = utc_now() - timedelta(days=1)
    assert await repo.recover() == []
    row, _ = await repo.claim(task.id, "worker")
    async with sessions() as session, session.begin():
        record = await session.get(WatermarkTaskRow, task.id)
        record.lease_expires_at = utc_now() - timedelta(minutes=5)
    assert await repo.recover() == [row.object_key]
    assert not await repo.finish(task.id, "worker", 1, size=20, sha256="a" * 64)
    assert await repo.recover() == [row.object_key]
    await repo.cleaned(row.object_key)
    assert await repo.recover() == []
    async with sessions() as session:
        assert (await session.get(ArtifactRow, source.artifact_id)).deleted_at is None


async def test_failure_can_retry_without_platform_download(setup):
    _, source, repo = setup
    first = await create(source, repo)
    await repo.claim(first.id, "worker")
    assert await repo.finish(first.id, "worker", 1, error="processing_failed")
    await repo.release(first.id, "worker", 1)
    retry = await create(source, repo, str(uuid4()))
    assert retry.id != first.id
    assert retry.job_id == source.download_id


async def test_no_detection_keeps_only_original(setup):
    _, source, repo = setup
    task = await create(source, repo)
    await repo.claim(task.id, "worker")
    assert await repo.finish(task.id, "worker", 1, unchanged=True)
    state = await repo.for_job(source.download_id, source.owner_hash)
    assert state.items[0].status == "unchanged"
    with pytest.raises(ApplicationError):
        await repo.artifact(task.id, source.owner_hash)


async def test_automatic_admission_failure_preserves_verified_file(setup):
    from app.models import DownloadJobRow
    from app.repositories.quota_admission import lock_admission
    from app.repositories.watermark import enqueue_automatic
    from app.services.quotas import QuotaPolicy

    sessions, source, repo = setup
    async with sessions() as session, session.begin():
        await lock_admission(session, source.owner_hash)
        job = await session.get(DownloadJobRow, source.download_id)
        artifact = await session.get(ArtifactRow, source.artifact_id)
        await enqueue_automatic(session, job, artifact, QuotaPolicy(storage_bytes=1))
    state = await repo.for_job(source.download_id, source.owner_hash)
    assert state.items[0].status == "failed"
    assert state.items[0].error_code == "storage_quota_exceeded"
    async with sessions() as session:
        assert (
            await session.get(DownloadJobRow, source.download_id)
        ).status == "succeeded"
        assert (
            await session.get(ArtifactRow, source.artifact_id)
        ).sha256 == source.sha256


async def test_deleting_original_cancels_queued_auto_task(setup):
    sessions, source, repo = setup
    task = await create(source, repo)
    deletion = DownloadDeleteRepository(sessions)
    await deletion.prepare_download_deletion(
        source.download_id, source.owner_hash, now=utc_now()
    )
    assert await repo.claim(task.id, "worker") is None
    await deletion.finish_download_deletion(source.download_id, source.owner_hash)
    async with sessions() as session:
        assert await session.get(WatermarkTaskRow, task.id) is None
