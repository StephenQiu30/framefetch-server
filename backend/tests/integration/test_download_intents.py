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
from app.services.provider_failures import ProviderFailure
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from tests.postgres import isolated_postgres_engine
from tests.resolution import start_attempt

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


async def test_duplicate_delivery_cannot_replace_a_live_operation(postgres_engine):
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    claims = await asyncio.gather(
        *(
            start_attempt(repo, accepted.id, 0, "operation-1", now=NOW)
            for _ in range(20)
        )
    )
    fresh = [claim for claim in claims if claim is not None]
    assert len(fresh) == 1 and fresh[0].intent.attempt == 1
    first = fresh[0]
    assert (
        await start_attempt(repo, accepted.id, 0, "operation-2", now=NOW + LEASE)
        is None
    )
    recovered = await repository(postgres_engine).running_operation(accepted.id, 0)
    assert recovered.execution == first.execution
    result = inspection(first.intent)
    completed = await repo.complete(first.intent, result, now=NOW + LEASE)
    assert completed.status == "ready" and completed.inspection_id == result.id
    assert await repo.complete(first.intent, result, now=NOW + LEASE) == completed
    assert await count(postgres_engine, MediaInspectionRow) == 1
    assert await count(postgres_engine, MediaFormatRow) == 1
    assert (
        await start_attempt(repo, accepted.id, 0, "after-ack-loss", now=NOW + LEASE)
        is None
    )


async def test_result_transaction_failure_keeps_intent_recoverable(
    postgres_engine: AsyncEngine,
) -> None:
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    lease = await start_attempt(
        repo,
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
        await start_attempt(
            repo, accepted.id, 0, "after-commit-failure", now=NOW + LEASE
        )
        is None
    )
    result = inspection(lease.intent)
    ready = await repo.complete(lease.intent, result, now=NOW + LEASE)
    assert ready.status == "ready"
    assert await count(postgres_engine, MediaInspectionRow) == 1


async def test_cancel_completion_race_never_revives_intent(
    postgres_engine: AsyncEngine,
) -> None:
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    lease = await start_attempt(
        repo,
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
        await start_attempt(
            repo,
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
        lease = await start_attempt(
            repo,
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
                await start_attempt(
                    repo, accepted.id, 0, "too-early", now=now + timedelta(seconds=9)
                )
        else:
            assert failed.status == "failed"
    assert failed.remaining_budget_ms == 180000
    assert failed.deadline == accepted.deadline
    queued = await repo.accept(replace(command(), idempotency_key="queued"), now=NOW)
    assert (
        await start_attempt(
            repo,
            queued.id,
            (await repo.execution_state(queued.id)).generation,
            str(uuid4()),
            now=NOW + timedelta(seconds=180),
        )
        is None
    )
    assert (await repo.get(queued.id, OWNER)).status == "expired"


async def test_network_failures_still_consume_three_attempts(
    postgres_engine: AsyncEngine,
) -> None:
    repo = repository(postgres_engine)
    accepted = await repo.accept(
        replace(command(), access_policy=ProviderAccessPolicy.PUBLIC), now=NOW
    )
    for attempt in range(3):
        now = NOW + timedelta(seconds=attempt * 15)
        lease = await start_attempt(
            repo,
            accepted.id,
            (await repo.execution_state(accepted.id)).generation,
            str(uuid4()),
            now=now,
        )
        assert lease is not None and lease.intent.attempt == attempt + 1
        failed = await repo.fail(
            lease.intent,
            now=now,
            reason_code="provider_temporarily_unavailable",
            failure=ProviderFailure.for_code("network_transient"),
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
    lease = await repo.claim_preparation(
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
    )
    assert deferred.status == "retry_wait" and deferred.attempt == 0
    cancelled = await repo.cancel(waiting.id, OWNER, now=NOW + timedelta(seconds=5))
    assert cancelled.status == "cancelled"
    assert (
        await repo.claim_preparation(
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
    lease = await repo.claim_preparation(
        expired.id,
        (await repo.execution_state(expired.id)).generation,
        str(uuid4()),
        now=NOW,
    )
    assert lease is not None
    waiting = await repo.fail(
        lease.intent, now=NOW, reason_code="provider_session_not_ready"
    )
    assert (
        await repo.claim_preparation(
            expired.id, 0, "no-auto-retry", now=NOW + timedelta(minutes=5)
        )
        is None
    )
    result = await repo.get(expired.id, OWNER)
    assert result.status == "expired" and result.remaining_budget_ms == 180000


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
    lease = await start_attempt(
        repo,
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
        lease = await start_attempt(
            repo,
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
        # Simulate an accepted manual wait from the version being replaced.
        # Current DDL must converge it once, preserving facts and cancellation.
        old = await repo.accept(
            replace(command(), id=uuid4(), idempotency_key="retired-wait"), now=NOW
        )
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "ALTER TABLE download_intents DROP CONSTRAINT "
                    "ck_download_intents_status"
                )
            )
            await connection.execute(
                text("ALTER TABLE download_intents ADD COLUMN authorization_id UUID")
            )
            await connection.execute(
                text(
                    "ALTER TABLE download_intents ADD COLUMN "
                    "authorization_deadline TIMESTAMPTZ"
                )
            )
            await connection.execute(
                text(
                    "UPDATE download_intents SET status='action_required', "
                    "reason_code='provider_session_not_ready', "
                    "authorization_id=:wait_id, "
                    "authorization_deadline=:wait_deadline WHERE id=:id"
                ),
                {
                    "id": old.id,
                    "wait_id": uuid4(),
                    "wait_deadline": NOW + timedelta(hours=24),
                },
            )
        resumed_event_id = uuid4()
        resumed_event = OutboxEventRow(
            id=resumed_event_id,
            aggregate_type="download_intent",
            aggregate_id=old.id,
            aggregate_version=1,
            event_type="download.intent.resumed",
            payload={
                "intent_id": str(old.id),
                "generation": 0,
                "wait_id": str(uuid4()),
            },
            available_at=NOW,
            created_at=NOW,
        )
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(resumed_event)
        await apply_schema()
        retired = await repo.get(old.id, OWNER)
        assert (
            retired.status == "failed"
            and retired.reason_code == "provider_session_not_ready"
        )
        assert retired.fence == old.fence + 1 and retired.generation == old.generation
        assert (
            retired.deadline == old.deadline
            and retired.remaining_budget_ms == old.remaining_budget_ms
        )
        async with async_sessionmaker(engine)() as session:
            cancelled = (
                await session.scalars(
                    select(OutboxEventRow).where(
                        OutboxEventRow.aggregate_id == old.id,
                        OutboxEventRow.event_type == "download.intent.cancelled",
                    )
                )
            ).all()
            assert len(cancelled) == 1 and cancelled[0].payload == {
                "intent_id": str(old.id),
                "generation": 0,
            }
            assert (
                await session.get(OutboxEventRow, resumed_event_id)
            ).published_at is not None
        await apply_schema()
        assert await repo.get(old.id, OWNER) == retired
        assert (await repo.get(accepted.id, OWNER)).status == "ready"
        assert await count(engine, MediaInspectionRow) == 1


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
        lease = await repo.claim_preparation(
            accepted.id,
            (await repo.execution_state(accepted.id)).generation,
            str(uuid4()),
            now=now,
        )
        assert lease is not None and lease.intent.attempt == 0
        waiting = await repo.fail(
            lease.intent,
            now=now,
            reason_code="provider_session_not_ready",
            retry_at=now + timedelta(seconds=15),
        )
        assert waiting.attempt == 0 and waiting.status == "retry_wait"
        assert waiting.id == accepted.id and waiting.generation == 0
        assert waiting.deadline == accepted.deadline
        assert waiting.retry_at == now + timedelta(seconds=15)
    now = NOW + timedelta(seconds=75)
    lease = await start_attempt(
        repo,
        accepted.id,
        (await repo.execution_state(accepted.id)).generation,
        str(uuid4()),
        now=now,
    )
    assert lease is not None
    ready = await repo.complete(lease.intent, inspection(lease.intent), now=now)
    assert ready.status == "ready" and ready.attempt == 1
    assert await count(postgres_engine, DownloadIntentRow) == 1


async def test_unavailable_source_stops_with_its_cause_before_original_deadline(
    postgres_engine,
):
    repo = repository(postgres_engine)
    accepted = await repo.accept(
        replace(command(), access_policy=ProviderAccessPolicy.OPERATOR_PUBLIC), now=NOW
    )
    for index in range(12):
        now = NOW + timedelta(seconds=index * 15)
        preparing = await repo.claim_preparation(
            accepted.id, 0, f"automatic-preparation-{index}", now=now
        )
        stopped = await repo.fail(
            preparing.intent, now=now, reason_code="provider_session_not_ready"
        )
        assert stopped.attempt == 0 and stopped.remaining_budget_ms == 180000
        assert stopped.deadline == accepted.deadline and stopped.generation == 0
    assert stopped.status == "failed" and stopped.retry_at is None
    assert stopped.reason_code == "provider_session_not_ready"
    assert stopped.latest_failure.code == "provider_session_not_ready"
    assert (
        await repo.claim_preparation(
            accepted.id, 0, "after-stop", now=NOW + timedelta(seconds=170)
        )
        is None
    )


async def test_late_result_at_deadline_expires_without_leaving_running_projection(
    postgres_engine,
):
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    operation = await start_attempt(repo, accepted.id, 0, "attempt-1", now=NOW)
    final = await repo.complete(
        operation.intent, inspection(operation.intent), now=accepted.deadline
    )
    assert final.status == "expired"
    assert final.reason_code == "inspection_timeout"
    assert final.operation_id is None
    assert await count(postgres_engine, MediaInspectionRow) == 0


async def test_unknown_outcome_cannot_be_replaced_or_refreshed(postgres_engine):
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    first = await start_attempt(repo, accepted.id, 0, "old", now=NOW)
    assert await start_attempt(repo, accepted.id, 0, "new", now=NOW) is None
    final = await repo.fail_generation(accepted.id, 0, now=NOW)
    assert final.latest_failure.failure_class == "outcome_unknown"
    with pytest.raises(RepositoryConflict):
        await repo.complete(first.intent, inspection(first.intent), now=NOW)
    with pytest.raises(RepositoryConflict, match="unconfirmed"):
        await repo.refresh(accepted.id, OWNER, now=NOW)


async def test_automatic_changed_session_recovery_is_owned_fenced_and_keeps_budget(
    postgres_engine,
):
    repo = repository(postgres_engine)
    accepted = await repo.accept(
        replace(command(), access_policy=ProviderAccessPolicy.PERSONAL_ENTITLED),
        now=NOW,
    )
    operation = await start_attempt(repo, accepted.id, 0, "first", now=NOW)
    waiting = await repo.fail(
        operation.intent,
        now=NOW + timedelta(seconds=10),
        reason_code="provider_auth_required",
    )
    assert waiting.status == "retry_wait" and waiting.retry_at == NOW + timedelta(
        seconds=25
    )
    assert (
        waiting.remaining_budget_ms == 170000 and waiting.deadline == accepted.deadline
    )
    assert waiting.operation_id is None and waiting.generation == 0
    with pytest.raises(RepositoryNotFound):
        await repo.get(waiting.id, "f" * 64)
    with pytest.raises(RepositoryConflict, match="timer"):
        await repo.claim_preparation(
            waiting.id, 0, "too-soon", now=NOW + timedelta(seconds=24)
        )
    with pytest.raises(RepositoryConflict):
        await repo.complete(
            operation.intent,
            inspection(operation.intent),
            now=NOW + timedelta(seconds=25),
        )
    second = await start_attempt(
        repo,
        waiting.id,
        0,
        "changed-source",
        now=NOW + timedelta(seconds=25),
        credential="changed-session",
    )
    assert second.intent.attempt == 2 and second.intent.remaining_budget_ms == 170000
    assert second.intent.deadline == accepted.deadline
    ready = await repo.complete(
        second.intent, inspection(second.intent), now=NOW + timedelta(seconds=30)
    )
    assert (
        ready.status == "ready"
        and ready.generation == 0
        and ready.remaining_budget_ms == 165000
    )
    async with async_sessionmaker(postgres_engine)() as session:
        assert (
            await session.scalar(select(func.count()).select_from(OutboxEventRow)) == 1
        )


async def test_unchanged_approved_session_stops_without_another_platform_call(
    postgres_engine,
):
    repo = repository(postgres_engine)
    accepted = await repo.accept(
        replace(command(), access_policy=ProviderAccessPolicy.PERSONAL_ENTITLED),
        now=NOW,
    )
    operation = await start_attempt(repo, accepted.id, 0, "first", now=NOW)
    waiting = await repo.fail(
        operation.intent, now=NOW, reason_code="provider_auth_required"
    )
    assert waiting.status == "retry_wait" and waiting.attempt == 1
    assert (
        await start_attempt(repo, accepted.id, 0, "same-source", now=waiting.retry_at)
        is None
    )
    stopped = await repo.get(accepted.id, OWNER)
    assert stopped.status == "failed" and stopped.attempt == 1
    assert stopped.latest_failure.code == "provider_auth_required"
    assert (
        stopped.remaining_budget_ms == 180000 and stopped.deadline == accepted.deadline
    )
    assert (
        await repo.claim_preparation(
            accepted.id, 0, "later", now=NOW + timedelta(seconds=30)
        )
        is None
    )
    async with async_sessionmaker(postgres_engine)() as session:
        assert (
            await session.scalar(select(func.count()).select_from(OutboxEventRow)) == 1
        )
