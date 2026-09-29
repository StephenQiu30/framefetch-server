from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models import AnalysisRunRow
from app.repositories.analysis import repository_retry as retry_module
from app.repositories.analysis.repository import SqlAlchemyAnalysisRepository
from app.repositories.analysis.repository_retry import AnalysisRetryRepository
from app.services.analysis.errors import PersistenceRetryLimited
from app.services.analysis.models import AnalysisRetry
from sqlalchemy import func, select
from tests.unit.repositories.analysis.factories import analysis_command, seed_artifact

NOW = datetime(2026, 9, 5, tzinfo=UTC)


@pytest.mark.parametrize(
    "lock_enabled", [True, False], ids=["owner-lock", "negative-control"]
)
async def test_concurrent_different_jobs_share_one_owner_retry_budget(
    analysis_db, monkeypatch, lock_enabled
):
    commands = []
    for index in range(2):
        source = await seed_artifact(analysis_db.sessions, NOW)
        initial = analysis_command(source)
        repo = analysis_db.repository
        await repo.create_job_and_enqueue(initial, now=NOW)
        await repo.claim_run(
            initial.id, initial.run_id, 1, "worker", NOW, timedelta(seconds=30)
        )
        await repo.complete_failure(
            initial.id,
            "worker",
            1,
            error_code="analysis_cli_failed",
            error_message="failed",
            retryable=False,
            now=NOW + timedelta(seconds=1),
        )
        commands.append(
            AnalysisRetry(
                job_id=initial.id,
                run_id=uuid4(),
                owner_hash=initial.owner_hash,
                idempotency_key=f"retry-{index}",
                trigger="manual_retry",
                outbox_event_id=uuid4(),
                max_attempts=3,
                retries_per_day=1,
            )
        )

    capacity_checks = 0
    starts = asyncio.Barrier(2)
    counted = asyncio.Barrier(2)
    original_lock = retry_module.lock_admission
    original_check = AnalysisRetryRepository._require_retry_capacity

    async def admission(session, owner_hash):
        await starts.wait()
        if lock_enabled:
            await original_lock(session, owner_hash)

    async def check_capacity(session, row, command, now):
        nonlocal capacity_checks
        capacity_checks += 1
        await original_check(session, row, command, now)
        # Only the lock-free control can have two transactions past this read.
        # A barrier here with the real lock would deadlock the test itself.
        if not lock_enabled:
            await counted.wait()

    monkeypatch.setattr(retry_module, "lock_admission", admission)
    monkeypatch.setattr(
        AnalysisRetryRepository, "_require_retry_capacity", staticmethod(check_capacity)
    )
    repo = SqlAlchemyAnalysisRepository(analysis_db.sessions)
    results = await asyncio.wait_for(
        asyncio.gather(
            *(
                repo.retry_job_and_enqueue(command, now=NOW + timedelta(seconds=2))
                for command in commands
            ),
            return_exceptions=True,
        ),
        timeout=10,
    )
    assert sum(isinstance(result, PersistenceRetryLimited) for result in results) == (
        1 if lock_enabled else 0
    )
    assert capacity_checks == 2
    assert sum(
        not isinstance(result, BaseException) and result.created for result in results
    ) == (1 if lock_enabled else 2)
    async with analysis_db.sessions() as session:
        assert await session.scalar(
            select(func.count())
            .select_from(AnalysisRunRow)
            .where(AnalysisRunRow.trigger == "manual_retry")
        ) == (1 if lock_enabled else 2)

    successful = next(
        command
        for command, result in zip(commands, results, strict=True)
        if not isinstance(result, BaseException)
    )
    # Replay is a single request and must not wait for the concurrency fixture.
    monkeypatch.setattr(retry_module, "lock_admission", original_lock)
    replay = await repo.retry_job_and_enqueue(
        successful, now=NOW + timedelta(seconds=3)
    )
    assert replay.created is False
