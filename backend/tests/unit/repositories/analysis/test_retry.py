from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models import (
    AnalysisArtifactLockRow,
    AnalysisRetryOperationRow,
    AnalysisRunRow,
    OutboxEventRow,
)
from app.services.analysis.errors import PersistenceActiveRun, PersistenceRetryLimited
from app.services.analysis.models import AnalysisRetry
from sqlalchemy import func, select
from tests.unit.repositories.analysis.factories import analysis_command, seed_artifact

NOW = datetime(2026, 8, 10, 10, tzinfo=UTC)


async def count_rows(analysis_db, model: type[object]) -> int:
    async with analysis_db.sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


@pytest.mark.asyncio
async def test_manual_retry_appends_run_and_replays_same_operation(analysis_db) -> None:
    source = await seed_artifact(analysis_db.sessions, NOW)
    initial = analysis_command(source)
    await analysis_db.repository.create_job_and_enqueue(initial, now=NOW)
    await analysis_db.repository.claim_run(
        initial.id,
        initial.run_id,
        1,
        "worker-a",
        NOW,
        timedelta(seconds=30),
    )
    failed = await analysis_db.repository.complete_failure(
        initial.id,
        "worker-a",
        1,
        error_code="analysis_cli_failed",
        error_message="failed",
        retryable=False,
        now=NOW + timedelta(seconds=1),
    )
    command = AnalysisRetry(
        job_id=initial.id,
        run_id=uuid4(),
        owner_hash=initial.owner_hash,
        idempotency_key="manual-retry",
        trigger="manual_retry",
        outbox_event_id=uuid4(),
        max_attempts=failed.max_attempts,
    )

    retried = await analysis_db.repository.retry_job_and_enqueue(
        command, now=NOW + timedelta(seconds=2)
    )
    replay = await analysis_db.repository.retry_job_and_enqueue(
        command, now=NOW + timedelta(seconds=3)
    )

    assert retried.created is True and replay.created is False
    assert retried.job.id == initial.id
    assert (retried.job.run_id, retried.job.run_no, retried.job.attempt) == (
        command.run_id,
        2,
        0,
    )
    assert await count_rows(analysis_db, AnalysisRunRow) == 2
    assert await count_rows(analysis_db, AnalysisRetryOperationRow) == 1
    assert await count_rows(analysis_db, AnalysisArtifactLockRow) == 1
    assert await count_rows(analysis_db, OutboxEventRow) == 2


@pytest.mark.asyncio
async def test_manual_retry_rejects_an_active_run(analysis_db) -> None:
    source = await seed_artifact(analysis_db.sessions, NOW)
    initial = analysis_command(source)
    await analysis_db.repository.create_job_and_enqueue(initial, now=NOW)

    with pytest.raises(PersistenceActiveRun):
        await analysis_db.repository.retry_job_and_enqueue(
            AnalysisRetry(
                job_id=initial.id,
                run_id=uuid4(),
                owner_hash=initial.owner_hash,
                idempotency_key="active-retry",
                trigger="manual_retry",
                outbox_event_id=uuid4(),
                max_attempts=3,
            ),
            now=NOW,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("max_runs_per_job", "min_interval_seconds"),
    ((1, 0), (10, 60)),
)
async def test_manual_retry_limits_leave_no_partial_facts(
    analysis_db, max_runs_per_job: int, min_interval_seconds: int
) -> None:
    source = await seed_artifact(analysis_db.sessions, NOW)
    initial = analysis_command(source)
    await analysis_db.repository.create_job_and_enqueue(initial, now=NOW)
    await analysis_db.repository.claim_run(
        initial.id,
        initial.run_id,
        1,
        "worker-a",
        NOW,
        timedelta(seconds=30),
    )
    await analysis_db.repository.complete_failure(
        initial.id,
        "worker-a",
        1,
        error_code="analysis_cli_failed",
        error_message="failed",
        retryable=False,
        now=NOW + timedelta(seconds=1),
    )
    before = {
        model: await count_rows(analysis_db, model)
        for model in (AnalysisRunRow, AnalysisRetryOperationRow, OutboxEventRow)
    }

    with pytest.raises(PersistenceRetryLimited):
        await analysis_db.repository.retry_job_and_enqueue(
            AnalysisRetry(
                job_id=initial.id,
                run_id=uuid4(),
                owner_hash=initial.owner_hash,
                idempotency_key="limited-retry",
                trigger="manual_retry",
                outbox_event_id=uuid4(),
                max_attempts=3,
                max_runs_per_job=max_runs_per_job,
                min_interval_seconds=min_interval_seconds,
            ),
            now=NOW + timedelta(seconds=2),
        )

    assert {
        model: await count_rows(analysis_db, model)
        for model in (AnalysisRunRow, AnalysisRetryOperationRow, OutboxEventRow)
    } == before
