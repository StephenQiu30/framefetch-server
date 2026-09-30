"""Expired results resume bounded original work, never a new admission or job."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from app.models import MediaInspectionRow, OutboxEventRow, ResourceAdmissionRow
from app.repositories.errors import RepositoryConflict, RepositoryNotFound
from app.services.downloads.errors import ApplicationError, ApplicationErrorCode
from app.services.downloads.queries import GetInspection
from app.services.quotas import QuotaExceeded, UserQuota
from sqlalchemy import func, select
from tests.integration.test_download_intents import (
    NOW,
    OWNER,
    command,
    inspection,
    repository,
)
from tests.integration.test_intent_handoff import ready
from tests.resolution import start_attempt


async def resolved(engine):
    repo = repository(engine)
    item = await repo.accept(command(), now=NOW)
    lease = await start_attempt(
        repo,
        item.id,
        (await repo.execution_state(item.id)).generation,
        str(uuid4()),
        now=NOW,
    )
    saved = await repo.complete(
        lease.intent, inspection(lease.intent), now=NOW + timedelta(seconds=5)
    )
    return repo, saved


def refreshed_result(lease, now):
    result = inspection(lease.intent)
    expires = now + timedelta(hours=1)
    return replace(
        result,
        expires_at=expires,
        formats=tuple(replace(f, expires_at=expires) for f in result.formats),
    )


async def test_concurrent_explicit_refresh_starts_one_new_generation_and_outbox(
    postgres_engine,
):
    repo, original = await resolved(postgres_engine)
    now = NOW + timedelta(hours=2)
    results = await asyncio.gather(
        *(repo.refresh(original.id, OWNER, now=now) for _ in range(30))
    )
    assert len({item.version for item in results}) == 1
    resumed = results[0]
    assert resumed.status == "queued"
    assert resumed.id == original.id
    assert resumed.inspection_id == original.inspection_id
    assert original.remaining_budget_ms == 175000
    assert resumed.remaining_budget_ms == 180000
    assert resumed.deadline == now + timedelta(seconds=180)
    assert resumed.attempt == 0 and original.attempt == 1
    assert resumed.generation == original.generation + 1
    lease = await start_attempt(
        repo,
        original.id,
        (await repo.execution_state(original.id)).generation,
        str(uuid4()),
        now=now,
    )
    assert lease.intent.fence > original.fence
    result = refreshed_result(lease, now)
    completed = await repo.complete(
        lease.intent, result, now=now + timedelta(seconds=3)
    )
    assert completed.status == "ready"
    assert completed.inspection_id == result.id != original.inspection_id
    assert completed.remaining_budget_ms == 177000
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async with async_sessionmaker(postgres_engine)() as session:
        assert (
            await session.scalar(select(func.count()).select_from(OutboxEventRow)) == 2
        )
        assert (
            await session.scalar(select(func.count()).select_from(ResourceAdmissionRow))
            == 1
        )
        assert (
            await session.scalar(select(func.count()).select_from(MediaInspectionRow))
            == 2
        )


async def test_valid_or_handed_off_result_does_not_refresh(postgres_engine):
    _, repo, downloads, item, create = await ready(postgres_engine)
    assert await repo.refresh(item.id, OWNER, now=NOW + timedelta(seconds=10)) == item
    job = await downloads.create_job(create, now=NOW)
    handed = await repo.get(item.id, OWNER)
    assert await repo.refresh(item.id, OWNER, now=NOW + timedelta(days=1)) == handed
    assert handed.job_id == job.job.id


async def test_refresh_has_owner_isolation_and_cancellation_wins(postgres_engine):
    repo, original = await resolved(postgres_engine)
    now = NOW + timedelta(hours=2)
    with pytest.raises(RepositoryNotFound):
        await repo.refresh(original.id, "b" * 64, now=now)
    await asyncio.gather(
        repo.refresh(original.id, OWNER, now=now),
        repo.cancel(original.id, OWNER, now=now),
        return_exceptions=True,
    )
    assert (await repo.get(original.id, OWNER)).status == "cancelled"
    with pytest.raises(RepositoryConflict):
        await repo.refresh(original.id, OWNER, now=now)
    assert (
        await start_attempt(
            repo,
            original.id,
            (await repo.execution_state(original.id)).generation,
            str(uuid4()),
            now=now,
        )
        is None
    )


async def test_refresh_rechecks_active_capacity_without_another_daily_charge(
    postgres_engine,
):
    repo, original = await resolved(postgres_engine)
    now = NOW + timedelta(hours=2)
    other = await repo.accept(
        replace(command(), id=uuid4(), idempotency_key="other"), now=now
    )
    quota = UserQuota(max_active_per_owner=1, daily_tasks=1)
    with pytest.raises(QuotaExceeded, match="active_task_quota_exceeded"):
        await repo.refresh(original.id, OWNER, now=now, quota=quota)
    assert await repo.get(original.id, OWNER) == original
    await repo.cancel(other.id, OWNER, now=now)
    assert (
        await repo.refresh(original.id, OWNER, now=now, quota=quota)
    ).status == "queued"


@pytest.mark.parametrize("change", ["id", "kind"])
async def test_changed_source_cannot_replace_the_original_result(
    postgres_engine, change
):
    repo, original = await resolved(postgres_engine)
    now = NOW + timedelta(hours=2)
    await repo.refresh(original.id, OWNER, now=now)
    lease = await start_attempt(
        repo,
        original.id,
        (await repo.execution_state(original.id)).generation,
        str(uuid4()),
        now=now,
    )
    result = refreshed_result(lease, now)
    result = replace(
        result,
        **(
            {"provider_media_id": "another-video"}
            if change == "id"
            else {"metadata": {**result.metadata, "media_kind": "image_gallery"}}
        ),
    )
    failed = await repo.complete(lease.intent, result, now=now)
    assert failed.status == "failed"
    assert failed.reason_code == "unsupported_source"
    assert failed.inspection_id == original.inspection_id


async def test_only_explicit_refresh_resets_generation_attempt_limit(postgres_engine):
    repo, item = await resolved(postgres_engine)
    for attempt in (2, 3):
        now = NOW + timedelta(hours=attempt * 2)
        await repo.refresh(item.id, OWNER, now=now)
        lease = await start_attempt(
            repo,
            item.id,
            (await repo.execution_state(item.id)).generation,
            str(uuid4()),
            now=now,
        )
        item = await repo.complete(
            lease.intent, refreshed_result(lease, now), now=now + timedelta(seconds=1)
        )
        assert item.attempt == 1
        assert item.generation == attempt - 1
    refreshed = await repo.refresh(item.id, OWNER, now=NOW + timedelta(days=1))
    assert refreshed.status == "queued"
    assert refreshed.generation == 3 and refreshed.attempt == 0


async def test_expired_inspection_preserves_metadata_and_ownership_without_formats(
    postgres_engine,
):
    _, repo, downloads, intent, _ = await ready(postgres_engine)
    get = GetInspection(downloads, now=lambda: NOW + timedelta(hours=2))
    expired = await get(intent.inspection_id, OWNER)
    assert expired.id == intent.inspection_id
    assert expired.formats == ()
    assert expired.expires_at < NOW + timedelta(hours=2)
    with pytest.raises(ApplicationError) as error:
        await get(intent.inspection_id, "b" * 64)
    assert error.value.code is ApplicationErrorCode.NOT_FOUND
