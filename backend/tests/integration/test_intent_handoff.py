import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
from app.models import DownloadJobRow, OutboxEventRow
from app.repositories.downloads.intent_repository import IntentRepository
from app.repositories.downloads.repository import SqlAlchemyDownloadRepository
from app.repositories.errors import (
    IdempotencyConflict,
    RepositoryConflict,
    RepositoryNotFound,
)
from app.services.downloads.download_models import DownloadCreate
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.integration.test_download_intents import (
    NOW,
    OWNER,
    command,
    inspection,
)


async def ready(engine):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    intents = IntentRepository(sessions)
    downloads = SqlAlchemyDownloadRepository(sessions)
    accepted = await intents.accept(command(), now=NOW)
    lease = await intents.begin_attempt(
        accepted.id,
        (await intents.execution_state(accepted.id)).generation,
        str(uuid4()),
        now=NOW,
    )
    result = inspection(lease.intent)
    saved = await intents.complete(lease.intent, result, now=NOW)
    create = DownloadCreate(
        uuid4(),
        result.id,
        result.formats[0].id,
        OWNER,
        "confirm",
        "e" * 64,
        {"height": 720},
    )
    return sessions, intents, downloads, saved, create


async def test_fifty_confirmations_keep_one_job_and_one_event(postgres_engine):
    sessions, intents, downloads, intent, create = await ready(postgres_engine)
    results = await asyncio.gather(
        *(
            downloads.create_job(
                replace(create, id=uuid4(), idempotency_key=f"confirm-{i}"), now=NOW
            )
            for i in range(50)
        )
    )
    assert len({result.job.id for result in results}) == 1
    assert sum(result.created for result in results) == 1
    saved = await intents.get(intent.id, OWNER)
    assert saved.status == "handed_off" and saved.job_id == results[0].job.id
    async with sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(DownloadJobRow)) == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OutboxEventRow)
                .where(OutboxEventRow.event_type == "download.requested")
            )
            == 1
        )
    with pytest.raises(IdempotencyConflict):
        await downloads.create_job(
            replace(create, request_fingerprint="f" * 64), now=NOW
        )
    with pytest.raises(RepositoryNotFound):
        await downloads.create_job(replace(create, owner_hash="z" * 64), now=NOW)


async def test_cancel_and_confirm_race_cannot_leave_an_active_job(postgres_engine):
    sessions, intents, downloads, intent, create = await ready(postgres_engine)
    outcomes = await asyncio.gather(
        downloads.create_job(create, now=NOW),
        intents.cancel(intent.id, OWNER, now=NOW),
        return_exceptions=True,
    )
    assert not isinstance(outcomes[1], Exception)
    assert (await intents.get(intent.id, OWNER)).status == "cancelled"
    async with sessions() as session:
        jobs = list(await session.scalars(select(DownloadJobRow)))
        assert all(
            job.status == "cancelled" and job.lease_owner is None for job in jobs
        )
    with pytest.raises(RepositoryConflict):
        await downloads.create_job(replace(create, id=uuid4()), now=NOW)


async def test_outbox_failure_rolls_back_job_and_handoff(postgres_engine):
    sessions, intents, downloads, intent, create = await ready(postgres_engine)

    def fail(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO outbox_events"):
            raise RuntimeError("outbox failure")

    event.listen(postgres_engine.sync_engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="outbox failure"):
            await downloads.create_job(create, now=NOW)
    finally:
        event.remove(postgres_engine.sync_engine, "before_cursor_execute", fail)
    assert (await intents.get(intent.id, OWNER)).status == "ready"
    async with sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(DownloadJobRow)) == 0
        )
    result = await downloads.create_job(create, now=NOW)
    assert result.created


async def test_deletion_releases_reference_without_resurrecting_intent(postgres_engine):
    _, intents, downloads, intent, create = await ready(postgres_engine)
    job = (await downloads.create_job(create, now=NOW)).job
    await intents.cancel(intent.id, OWNER, now=NOW)
    await downloads.prepare_download_deletion(job.id, OWNER, now=NOW)
    await downloads.finish_download_deletion(job.id, OWNER)
    saved = await intents.get(intent.id, OWNER)
    assert saved.status == "expired" and saved.job_id is None
    with pytest.raises(RepositoryConflict):
        await downloads.create_job(replace(create, id=uuid4()), now=NOW)


async def test_explicit_history_retry_preserves_original_handoff(postgres_engine):
    _, intents, downloads, intent, create = await ready(postgres_engine)
    original = (await downloads.create_job(create, now=NOW)).job
    await downloads.cancel_job(original.id, OWNER, NOW)
    retried = await downloads.create_job(
        replace(
            create,
            id=uuid4(),
            idempotency_key="retry",
            request_fingerprint="f" * 64,
            allow_expired_source=True,
        ),
        now=NOW,
    )
    assert retried.created and retried.job.id != original.id
    assert (await intents.get(intent.id, OWNER)).job_id == original.id
