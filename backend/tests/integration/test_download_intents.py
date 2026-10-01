"""Intent ownership, one Activity result, cancellation and atomic persistence."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.models import MediaInspectionRow, OutboxEventRow
from app.models.download_intent import DownloadIntentRow
from app.repositories.downloads.intent_repository import IntentRepository
from app.repositories.errors import (
    IdempotencyConflict,
    RepositoryConflict,
    RepositoryNotFound,
)
from app.services.downloads.inspection_models import (
    EncryptedUrl,
    FormatCreate,
    InspectionCreate,
)
from app.services.downloads.intent_models import IntentCreate, IntentSnapshot
from app.services.provider_types import ExecutionContext
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.postgres import isolated_postgres_engine

NOW = datetime(2026, 10, 1, tzinfo=UTC)
OWNER = "a" * 64


def command() -> IntentCreate:
    return IntentCreate(
        uuid4(),
        OWNER,
        "parse-once",
        "b" * 64,
        EncryptedUrl(b"ciphertext", b"nonce", "test"),
    )


def inspection(intent: IntentSnapshot) -> InspectionCreate:
    expires = NOW + timedelta(hours=1)
    return InspectionCreate(
        id=uuid4(),
        owner_hash=intent.owner_hash,
        idempotency_key=f"intent:{intent.id}:{intent.generation}",
        request_fingerprint="c" * 64,
        url_ciphertext=b"ciphertext",
        url_nonce=b"nonce",
        url_key_id="test",
        extractor_key="Example",
        provider_media_id="sample",
        title="Sample",
        duration_seconds=10,
        metadata={
            "execution_context": ExecutionContext(
                provider_key="generic",
                registry_revision="registry-test",
                resolved_layer="L1",
                client="yt-dlp-default",
                engine_revision="fixture",
                egress_route="default",
                egress_revision="egress-test",
                egress_class="unknown",
                egress_observed_ip=None,
                identity_used=False,
                identity_digest=None,
                browser_context_kind="none",
            ).to_document()
        },
        expires_at=expires,
        formats=(
            FormatCreate(uuid4(), "720p", "d" * 64, {"height": 720}, {}, expires),
        ),
    )


def repository(engine):
    return IntentRepository(async_sessionmaker(engine, expire_on_commit=False))


async def count(engine, model):
    async with async_sessionmaker(engine)() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def test_concurrent_acceptance_is_one_intent_and_atomic_outbox(postgres_engine):
    repo, request = repository(postgres_engine), command()
    results = await asyncio.gather(
        *(repo.accept(replace(request, id=uuid4()), now=NOW) for _ in range(20))
    )
    assert len({result.id for result in results}) == 1
    assert await count(postgres_engine, DownloadIntentRow) == 1
    assert await count(postgres_engine, OutboxEventRow) == 1
    with pytest.raises(IdempotencyConflict):
        await repo.accept(replace(request, request_fingerprint="f" * 64), now=NOW)
    with pytest.raises(RepositoryNotFound):
        await repo.get(results[0].id, "f" * 64)


async def test_cancel_stops_result_commit_and_duplicate_activity(postgres_engine):
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    operation = await repo.claim(accepted.id, 0, now=NOW)
    assert operation is not None
    assert await repo.claim(accepted.id, 0, now=NOW) is None
    assert (await repo.cancel(accepted.id, OWNER, now=NOW)).status == "cancelling"
    await repo.confirm_cancel(accepted.id, 0, now=NOW)
    with pytest.raises(RepositoryConflict):
        await repo.complete(operation.intent, inspection(operation.intent), now=NOW)
    assert await count(postgres_engine, MediaInspectionRow) == 0
    assert await count(postgres_engine, OutboxEventRow) == 2


async def test_result_commit_keeps_execution_context_and_owner(postgres_engine):
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    operation = await repo.claim(accepted.id, 0, now=NOW)
    result = inspection(operation.intent)
    for bad in (
        replace(result, owner_hash="f" * 64),
        replace(result, idempotency_key="foreign"),
    ):
        with pytest.raises(RepositoryConflict):
            await repo.complete(operation.intent, bad, now=NOW)
    ready = await repo.complete(operation.intent, result, now=NOW)
    assert ready.status == "ready"
    assert ready.execution_context.to_document() == result.metadata["execution_context"]
    assert await count(postgres_engine, MediaInspectionRow) == 1


async def test_outbox_failure_rolls_back_intent(postgres_engine):
    repo = repository(postgres_engine)

    def fail(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO outbox_events"):
            raise RuntimeError("outbox failure")

    event.listen(postgres_engine.sync_engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="outbox failure"):
            await repo.accept(command(), now=NOW)
    finally:
        event.remove(postgres_engine.sync_engine, "before_cursor_execute", fail)
    assert await count(postgres_engine, DownloadIntentRow) == 0


async def test_queue_and_late_result_respect_120_second_deadline(postgres_engine):
    repo = repository(postgres_engine)
    queued = await repo.accept(command(), now=NOW)
    assert queued.deadline == NOW + timedelta(seconds=120)
    assert await repo.claim(queued.id, 0, now=queued.deadline) is None
    assert (await repo.get(queued.id, OWNER)).status == "cancelling"
    await repo.confirm_cancel(queued.id, 0, now=queued.deadline)
    assert (await repo.get(queued.id, OWNER)).status == "expired"
    second = await repo.accept(replace(command(), idempotency_key="late"), now=NOW)
    operation = await repo.claim(second.id, 0, now=NOW)
    expired = await repo.complete(
        operation.intent, inspection(operation.intent), now=second.deadline
    )
    assert expired.status == "expired"
    assert await count(postgres_engine, MediaInspectionRow) == 0


async def test_sql_bootstrap_repeat_matches_orm_and_preserves_current_intent():
    sql = (Path(__file__).resolve().parents[2] / "sql/schema.sql").read_text()
    async with isolated_postgres_engine() as engine:

        async def apply():
            async with engine.connect() as connection:
                schema = await connection.scalar(text("SELECT current_schema()"))
                assert schema.startswith("test_") and schema.replace("_", "").isalnum()
                await connection.execute(text(f'SET search_path TO "{schema}", public'))
                await connection.commit()
                raw = await connection.get_raw_connection()
                await raw.driver_connection.execute(sql)

        await apply()
        repo = repository(engine)
        accepted = await repo.accept(command(), now=NOW)
        await apply()
        assert await repo.get(accepted.id, OWNER) == accepted
        async with engine.connect() as connection:
            columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema=current_schema() "
                            "AND table_name='download_intents'"
                        )
                    )
                ).scalars()
            )
        assert columns == set(DownloadIntentRow.__table__.columns.keys())
        assert await count(engine, OutboxEventRow) == 1


async def test_interrupted_resolve_expires_on_read_and_can_refresh(postgres_engine):
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    running = await repo.claim(accepted.id, 0, now=NOW)
    assert running.intent.status == "resolving"
    now = accepted.deadline
    expired = await repo.get(accepted.id, OWNER, now=now)
    assert expired.status == "cancelling"
    assert (await repo.get(accepted.id, OWNER, now=now)).version == expired.version
    await repo.confirm_cancel(accepted.id, 0, now=now)
    with pytest.raises(RepositoryConflict):
        await repo.complete(running.intent, inspection(running.intent), now=now)
    refreshed = await repo.refresh(accepted.id, OWNER, now=now)
    assert refreshed.generation == 1 and refreshed.status == "queued"
    assert refreshed.deadline == now + timedelta(seconds=120)


async def test_worker_restart_in_same_generation_rejects_old_result(postgres_engine):
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    old = await repo.claim(accepted.id, 0, now=NOW)
    recovered = await repo.claim(
        accepted.id, 0, now=NOW + timedelta(seconds=30), recover=True
    )
    assert recovered.intent.deadline == accepted.deadline
    assert recovered.intent.version > old.intent.version
    with pytest.raises(RepositoryConflict):
        await repo.complete(
            old.intent, inspection(old.intent), now=NOW + timedelta(seconds=31)
        )
    assert (
        await repo.complete(
            recovered.intent,
            inspection(recovered.intent),
            now=NOW + timedelta(seconds=31),
        )
    ).status == "ready"
    assert await count(postgres_engine, MediaInspectionRow) == 1
