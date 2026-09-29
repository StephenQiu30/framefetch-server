from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.models import MediaFormatRow, MediaInspectionRow, OutboxEventRow
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
from app.services.provider_access import ProviderAccessPolicy
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from tests.postgres import isolated_postgres_engine

NOW = datetime(2026, 9, 22, tzinfo=UTC)
OWNER = "a" * 64
LEASE = timedelta(seconds=15)


def command() -> IntentCreate:
    return IntentCreate(
        uuid4(),
        OWNER,
        "parse-once",
        "b" * 64,
        EncryptedUrl(b"ciphertext", b"nonce", "test"),
    )


def inspection(intent: IntentSnapshot) -> InspectionCreate:
    return InspectionCreate(
        id=uuid4(),
        owner_hash=intent.owner_hash,
        idempotency_key=f"intent:{intent.id}:{intent.fence}",
        request_fingerprint="c" * 64,
        url_ciphertext=b"ciphertext",
        url_nonce=b"nonce",
        url_key_id="test",
        extractor_key="Example",
        provider_media_id="sample",
        title="Sample",
        duration_seconds=10,
        metadata={"access_policy_id": intent.access_policy.value},
        expires_at=NOW + timedelta(hours=1),
        formats=(
            FormatCreate(
                uuid4(), "720p", "d" * 64, {"height": 720}, {}, NOW + timedelta(hours=1)
            ),
        ),
    )


def repository(engine: AsyncEngine) -> IntentRepository:
    return IntentRepository(async_sessionmaker(engine, expire_on_commit=False))


async def count(engine: AsyncEngine, model: type) -> int:
    async with async_sessionmaker(engine)() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def test_concurrent_acceptance_and_lost_response_recover_one_intent(
    postgres_engine: AsyncEngine,
) -> None:
    repo = repository(postgres_engine)
    request = command()
    results = await asyncio.gather(
        *(repo.accept(replace(request, id=uuid4()), now=NOW) for _ in range(50))
    )
    assert len({result.id for result in results}) == 1
    assert await count(postgres_engine, DownloadIntentRow) == 1
    assert await count(postgres_engine, OutboxEventRow) == 1
    # Recreate the adapter to model an API restart after commit/response loss.
    recovered = await repository(postgres_engine).accept(
        request, now=NOW + timedelta(seconds=5)
    )
    assert recovered.id == results[0].id
    assert recovered.deadline == NOW + timedelta(seconds=180)
    async with async_sessionmaker(postgres_engine)() as session:
        message = await session.scalar(select(OutboxEventRow))
        assert message.payload == {"intent_id": str(recovered.id), "generation": 0}
        assert message.aggregate_version == 0
    with pytest.raises(IdempotencyConflict):
        await repo.accept(
            replace(request, id=uuid4(), request_fingerprint="e" * 64), now=NOW
        )
    changed_policy = await repo.accept(
        replace(
            request, id=uuid4(), access_policy=ProviderAccessPolicy.OPERATOR_PUBLIC
        ),
        now=NOW,
    )
    assert changed_policy.id == recovered.id
    assert changed_policy.access_policy is ProviderAccessPolicy.PUBLIC
    with pytest.raises(RepositoryNotFound):
        await repo.get(recovered.id, "f" * 64)
    with pytest.raises(RepositoryNotFound):
        await repo.cancel(recovered.id, "f" * 64, now=NOW)
    other = await repo.accept(
        replace(request, id=uuid4(), owner_hash="f" * 64), now=NOW
    )
    assert other.id != recovered.id


async def test_outbox_write_failure_rolls_back_acceptance(
    postgres_engine: AsyncEngine,
) -> None:
    def fail_outbox(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO outbox_events"):
            raise RuntimeError("injected outbox failure")

    event.listen(postgres_engine.sync_engine, "before_cursor_execute", fail_outbox)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            await repository(postgres_engine).accept(command(), now=NOW)
    finally:
        event.remove(postgres_engine.sync_engine, "before_cursor_execute", fail_outbox)
    assert await count(postgres_engine, DownloadIntentRow) == 0
    assert await count(postgres_engine, OutboxEventRow) == 0


async def test_worker_restart_fences_old_completion_and_keeps_one_result(
    postgres_engine: AsyncEngine,
) -> None:
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    claims = await asyncio.gather(
        *(repo.begin_attempt(accepted.id, 0, "operation-1", now=NOW) for _ in range(20))
    )
    assert len({claim.intent.fence for claim in claims}) == 1
    first = claims[0]
    assert first.intent.attempt == 1
    # A new Temporal attempt supersedes the old one without a lease scan.
    second = await repo.begin_attempt(accepted.id, 0, "operation-2", now=NOW + LEASE)
    assert second.intent.fence > first.intent.fence
    assert second.intent.attempt == 2
    assert second.intent.deadline == accepted.deadline
    with pytest.raises(RepositoryConflict):
        await repo.complete(first.intent, inspection(first.intent), now=NOW + LEASE)
    result = inspection(second.intent)
    completed = await repo.complete(
        second.intent, result, now=NOW + LEASE + timedelta(seconds=1)
    )
    assert completed.status == "ready" and completed.inspection_id == result.id
    assert completed.operation_id is None
    assert await count(postgres_engine, MediaInspectionRow) == 1
    assert await count(postgres_engine, MediaFormatRow) == 1
    # ACK loss and later sweeps cannot execute a completed result again.
    assert (
        await repo.begin_attempt(
            accepted.id,
            (await repo.execution_state(accepted.id)).generation,
            str(uuid4()),
            now=NOW + LEASE,
        )
        is None
    )


async def test_result_transaction_failure_keeps_intent_recoverable(
    postgres_engine: AsyncEngine,
) -> None:
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    lease = await repo.begin_attempt(
        accepted.id,
        (await repo.execution_state(accepted.id)).generation,
        str(uuid4()),
        now=NOW,
    )
    assert lease is not None

    def fail_ready(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("UPDATE download_intents"):
            raise RuntimeError("injected result failure")

    event.listen(postgres_engine.sync_engine, "before_cursor_execute", fail_ready)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            await repo.complete(lease.intent, inspection(lease.intent), now=NOW)
    finally:
        event.remove(postgres_engine.sync_engine, "before_cursor_execute", fail_ready)
    assert await count(postgres_engine, MediaInspectionRow) == 0
    assert await count(postgres_engine, MediaFormatRow) == 0
    assert (await repo.get(accepted.id, OWNER)).status == "resolving"
    assert (
        await repo.begin_attempt(
            accepted.id, 0, "after-commit-failure", now=NOW + LEASE
        )
        is not None
    )


async def test_cancel_completion_race_never_revives_intent(
    postgres_engine: AsyncEngine,
) -> None:
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    lease = await repo.begin_attempt(
        accepted.id,
        (await repo.execution_state(accepted.id)).generation,
        str(uuid4()),
        now=NOW,
    )
    assert lease is not None
    results = await asyncio.gather(
        repo.cancel(accepted.id, OWNER, now=NOW),
        repo.complete(lease.intent, inspection(lease.intent), now=NOW),
        return_exceptions=True,
    )
    assert not isinstance(results[0], Exception)
    assert not isinstance(results[1], Exception) or isinstance(
        results[1], RepositoryConflict
    )
    cancelled = await repo.get(accepted.id, OWNER)
    assert cancelled.status == "cancelled"
    assert (await repo.cancel(accepted.id, OWNER, now=NOW)).version == cancelled.version
    with pytest.raises(RepositoryConflict):
        await repo.fail(lease.intent, now=NOW, reason_code="inspection_failed")
    assert (
        await repo.begin_attempt(
            accepted.id,
            (await repo.execution_state(accepted.id)).generation,
            str(uuid4()),
            now=NOW + LEASE,
        )
        is None
    )


async def test_retry_wait_budget_and_queue_deadline_are_not_reset(
    postgres_engine: AsyncEngine,
) -> None:
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    for attempt in range(3):
        now = NOW + timedelta(seconds=attempt * 10)
        lease = await repo.begin_attempt(
            accepted.id,
            (await repo.execution_state(accepted.id)).generation,
            str(uuid4()),
            now=now,
        )
        assert lease is not None and lease.intent.attempt == attempt + 1
        failed = await repo.fail(
            lease.intent,
            now=now,
            reason_code="provider_rate_limited",
            retry_at=now + timedelta(seconds=10),
        )
        if attempt < 2:
            assert failed.status == "retry_wait"
            with pytest.raises(RepositoryConflict, match="timer"):
                await repo.begin_attempt(
                    accepted.id, 0, "too-early", now=now + timedelta(seconds=9)
                )
        else:
            assert failed.status == "failed"
    assert failed.remaining_budget_ms == 160000
    assert failed.deadline == accepted.deadline
    queued = await repo.accept(replace(command(), idempotency_key="queued"), now=NOW)
    assert (
        await repo.begin_attempt(
            queued.id,
            (await repo.execution_state(queued.id)).generation,
            str(uuid4()),
            now=NOW + timedelta(seconds=180),
        )
        is None
    )
    assert (await repo.get(queued.id, OWNER)).status == "expired"


async def test_guest_media_failures_still_consume_three_attempts(
    postgres_engine: AsyncEngine,
) -> None:
    repo = repository(postgres_engine)
    accepted = await repo.accept(
        replace(command(), access_policy=ProviderAccessPolicy.PUBLIC_SESSION), now=NOW
    )
    for attempt in range(3):
        now = NOW + timedelta(seconds=attempt * 15)
        lease = await repo.begin_attempt(
            accepted.id,
            (await repo.execution_state(accepted.id)).generation,
            str(uuid4()),
            now=now,
        )
        assert lease is not None and lease.intent.attempt == attempt + 1
        failed = await repo.fail(
            lease.intent,
            now=now,
            reason_code="provider_guest_context_required",
            retry_at=now + timedelta(seconds=15),
        )
        if attempt < 2:
            assert failed.status == "retry_wait"
    assert failed.status == "failed" and failed.attempt == 3


async def test_session_preparation_wait_preserves_cancellation_and_deadline(
    postgres_engine: AsyncEngine,
) -> None:
    repo = repository(postgres_engine)
    waiting = await repo.accept(
        replace(command(), access_policy=ProviderAccessPolicy.OPERATOR_PUBLIC), now=NOW
    )
    lease = await repo.begin_attempt(
        waiting.id,
        (await repo.execution_state(waiting.id)).generation,
        str(uuid4()),
        now=NOW,
    )
    assert lease is not None
    deferred = await repo.fail(
        lease.intent,
        now=NOW,
        reason_code="provider_session_not_ready",
        retry_at=NOW + timedelta(seconds=15),
        preparation_wait=True,
    )
    assert deferred.status == "retry_wait" and deferred.attempt == 0
    cancelled = await repo.cancel(waiting.id, OWNER, now=NOW + timedelta(seconds=5))
    assert cancelled.status == "cancelled"
    assert (
        await repo.begin_attempt(
            waiting.id,
            (await repo.execution_state(waiting.id)).generation,
            str(uuid4()),
            now=NOW + timedelta(seconds=15),
        )
        is None
    )

    expired = await repo.accept(
        replace(
            command(),
            idempotency_key="expires-during-session-wait",
            id=uuid4(),
            access_policy=ProviderAccessPolicy.OPERATOR_PUBLIC,
        ),
        now=NOW,
    )
    lease = await repo.begin_attempt(
        expired.id,
        (await repo.execution_state(expired.id)).generation,
        str(uuid4()),
        now=NOW,
    )
    assert lease is not None
    await repo.fail(
        lease.intent,
        now=NOW,
        reason_code="provider_session_not_ready",
        retry_at=NOW + timedelta(seconds=15),
        preparation_wait=True,
    )
    assert (
        await repo.begin_attempt(
            expired.id, 0, "expired", now=NOW + timedelta(seconds=180)
        )
        is None
    )
    assert (await repo.get(expired.id, OWNER)).status == "expired"


async def test_cancel_is_atomic_with_one_durable_command(postgres_engine):
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    await asyncio.gather(*(repo.cancel(accepted.id, OWNER, now=NOW) for _ in range(20)))
    async with async_sessionmaker(postgres_engine)() as session:
        messages = (await session.scalars(select(OutboxEventRow))).all()
        assert sorted(m.event_type for m in messages) == [
            "download.intent.cancelled",
            "download.intent.requested",
        ]
        assert all(
            m.payload == {"intent_id": str(accepted.id), "generation": 0}
            for m in messages
        )


async def test_foreign_inspection_cannot_be_attached(
    postgres_engine: AsyncEngine,
) -> None:
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    lease = await repo.begin_attempt(
        accepted.id,
        (await repo.execution_state(accepted.id)).generation,
        str(uuid4()),
        now=NOW,
    )
    assert lease is not None
    result = inspection(lease.intent)
    for mismatch in (
        replace(result, owner_hash="f" * 64),
        replace(result, idempotency_key="foreign"),
        replace(result, metadata={"access_policy_id": "operator_public"}),
    ):
        with pytest.raises(RepositoryConflict):
            await repo.complete(lease.intent, mismatch, now=NOW)
    assert await count(postgres_engine, MediaInspectionRow) == 0


@pytest.mark.parametrize(
    "invalid",
    [
        {"status": "resolving"},
        {"status": "ready"},
        {"status": "handed_off"},
        {"status": "action_required"},
        {"attempt": 4},
        {"version": -1},
        {"generation": -1},
        {"remaining_budget_ms": 180001},
    ],
)
async def test_database_rejects_inconsistent_intent_state(
    postgres_engine: AsyncEngine, invalid: dict[str, object]
) -> None:
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    async with async_sessionmaker(postgres_engine)() as session, session.begin():
        with pytest.raises(IntegrityError):
            await session.execute(
                update(DownloadIntentRow)
                .where(DownloadIntentRow.id == accepted.id)
                .values(**invalid)
            )


async def test_sql_bootstrap_and_repeat_preserve_intent_and_outbox() -> None:
    sql = (Path(__file__).resolve().parents[2] / "sql/schema.sql").read_text()
    async with isolated_postgres_engine() as engine:

        async def apply_schema() -> None:
            async with engine.connect() as connection:
                schema = await connection.scalar(text("SELECT current_schema()"))
                assert schema.startswith("test_") and schema.replace("_", "").isalnum()
                await connection.execute(text(f'SET search_path TO "{schema}", public'))
                await connection.commit()
                raw = await connection.get_raw_connection()
                await raw.driver_connection.execute(sql)

        await apply_schema()
        repo = repository(engine)
        accepted = await repo.accept(command(), now=NOW)
        lease = await repo.begin_attempt(
            accepted.id,
            (await repo.execution_state(accepted.id)).generation,
            str(uuid4()),
            now=NOW,
        )
        assert lease is not None
        await apply_schema()
        reloaded = await repo.get(accepted.id, OWNER)
        assert reloaded == lease.intent
        assert await count(engine, OutboxEventRow) == 1
        await repo.complete(lease.intent, inspection(lease.intent), now=NOW)
        # ORM and SQL have exactly the same columns (including secret envelopes).
        async with engine.connect() as connection:
            columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = current_schema() "
                            "AND table_name = 'download_intents'"
                        )
                    )
                ).scalars()
            )
        assert columns == set(DownloadIntentRow.__table__.columns.keys())
        assert "url" not in columns


@pytest.mark.parametrize(
    "policy",
    [ProviderAccessPolicy.OPERATOR_PUBLIC, ProviderAccessPolicy.PERSONAL_ENTITLED],
)
async def test_cold_session_wait_keeps_one_intent_and_does_not_spend_parse_attempts(
    postgres_engine, policy
):
    repo = repository(postgres_engine)
    accepted = await repo.accept(replace(command(), access_policy=policy), now=NOW)
    for index in range(5):
        now = NOW + timedelta(seconds=index * 15)
        lease = await repo.begin_attempt(
            accepted.id,
            (await repo.execution_state(accepted.id)).generation,
            str(uuid4()),
            now=now,
        )
        assert lease is not None and lease.intent.attempt == 1
        waiting = await repo.fail(
            lease.intent,
            now=now,
            reason_code="provider_session_not_ready",
            retry_at=now + timedelta(seconds=15),
            preparation_wait=True,
        )
        assert waiting.attempt == 0 and waiting.status == "retry_wait"
        assert waiting.deadline == accepted.deadline and waiting.id == accepted.id
    now = NOW + timedelta(seconds=75)
    lease = await repo.begin_attempt(
        accepted.id,
        (await repo.execution_state(accepted.id)).generation,
        str(uuid4()),
        now=now,
    )
    assert lease is not None
    ready = await repo.complete(lease.intent, inspection(lease.intent), now=now)
    assert ready.status == "ready" and ready.attempt == 1
    assert await count(postgres_engine, DownloadIntentRow) == 1


async def test_late_result_at_deadline_expires_without_leaving_running_projection(
    postgres_engine,
):
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    operation = await repo.begin_attempt(accepted.id, 0, "attempt-1", now=NOW)
    final = await repo.complete(
        operation.intent, inspection(operation.intent), now=accepted.deadline
    )
    assert final.status == "expired"
    assert final.reason_code == "inspection_timeout"
    assert final.operation_id is None
    assert await count(postgres_engine, MediaInspectionRow) == 0


async def test_late_failure_cannot_invalidate_replacement_activity(postgres_engine):
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    first = await repo.begin_attempt(accepted.id, 0, "old", now=NOW)
    current = await repo.begin_attempt(accepted.id, 0, "new", now=NOW)
    with pytest.raises(RepositoryConflict):
        await repo.fail(first.intent, now=NOW, reason_code="inspection_timeout")
    assert await repo.execution_state(accepted.id) == current.intent
