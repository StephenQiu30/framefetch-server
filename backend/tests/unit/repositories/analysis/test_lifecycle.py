from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models import AnalysisStepResultRow
from app.models.analysis import AnalysisArtifactLockRow
from app.services.analysis.errors import PersistenceConflict, PersistenceNotFound
from app.services.analysis_execution.models import AnalysisStepStatus
from sqlalchemy import func, select
from tests.unit.repositories.analysis.factories import (
    analysis_command,
    seed_artifact,
)

NOW = datetime(2026, 8, 6, 8, tzinfo=UTC)


async def create_job(analysis_db, *, max_attempts: int = 3):
    source = await seed_artifact(analysis_db.sessions, NOW)
    command = analysis_command(source, max_attempts=max_attempts)
    await analysis_db.repository.create_job_and_enqueue(command, now=NOW)
    return source, command


async def lock_count(analysis_db) -> int:
    async with analysis_db.sessions() as session:
        statement = select(func.count()).select_from(AnalysisArtifactLockRow)
        return int(await session.scalar(statement) or 0)


@pytest.mark.asyncio
async def test_claim_and_heartbeat_enforce_lease_stage_and_progress(
    analysis_db,
) -> None:
    _, command = await create_job(analysis_db)
    claimed = await analysis_db.repository.claim_run(
        command.id,
        command.run_id,
        1,
        "worker-a",
        NOW,
        timedelta(seconds=30),
    )
    assert claimed is not None
    assert (claimed.status, claimed.stage, claimed.attempt, claimed.version) == (
        "running",
        "preparing",
        1,
        1,
    )
    assert await analysis_db.repository.heartbeat(
        command.id,
        "worker-a",
        1,
        stage="preparing",
        progress=30,
        now=NOW + timedelta(seconds=1),
        lease_for=timedelta(seconds=30),
    )
    with pytest.raises(PersistenceConflict):
        await analysis_db.repository.heartbeat(
            command.id,
            "worker-a",
            1,
            stage="validating",
            progress=80,
            now=NOW + timedelta(seconds=2),
            lease_for=timedelta(seconds=30),
        )
    with pytest.raises(PersistenceConflict):
        await analysis_db.repository.heartbeat(
            command.id,
            "worker-a",
            1,
            stage="preparing",
            progress=20,
            now=NOW + timedelta(seconds=2),
            lease_for=timedelta(seconds=30),
        )
    with pytest.raises(PersistenceNotFound):
        await analysis_db.repository.cancel_job(command.id, "b" * 64, NOW)

    cancelled = await analysis_db.repository.cancel_job(
        command.id, command.owner_hash, NOW + timedelta(seconds=1)
    )
    assert (cancelled.status, cancelled.error_code) == ("cancelled", "cancelled")
    assert await lock_count(analysis_db) == 0
    assert not await analysis_db.repository.heartbeat(
        command.id,
        "worker-a",
        1,
        stage="preparing",
        progress=20,
        now=NOW + timedelta(seconds=2),
        lease_for=timedelta(seconds=30),
    )


@pytest.mark.asyncio
async def test_retry_keeps_lock_until_terminal_failure(analysis_db) -> None:
    _, command = await create_job(analysis_db, max_attempts=2)
    await analysis_db.repository.claim_run(
        command.id,
        command.run_id,
        1,
        "worker-a",
        NOW,
        timedelta(seconds=30),
    )
    retry_at = NOW + timedelta(seconds=10)
    retrying = await analysis_db.repository.complete_failure(
        command.id,
        "worker-a",
        1,
        error_code="provider_unavailable",
        error_message="temporary",
        retryable=True,
        now=NOW + timedelta(seconds=1),
        retry_at=retry_at,
    )
    assert retrying.status == "retry_wait"
    assert await lock_count(analysis_db) == 1
    # The SkillWorkflow timer owns the retry; an early wake-up cannot claim.
    assert (
        await analysis_db.repository.claim_run(
            command.id, command.run_id, 1, "worker-b", NOW, timedelta(seconds=30)
        )
        is None
    )
    retried = await analysis_db.repository.claim_run(
        command.id,
        command.run_id,
        1,
        "worker-b",
        retry_at,
        timedelta(seconds=30),
    )
    assert retried is not None and (retried.attempt, retried.retry_at) == (2, None)
    failed = await analysis_db.repository.complete_failure(
        command.id,
        "worker-b",
        2,
        error_code="invalid_model_output",
        error_message="strict schema rejected",
        retryable=False,
        now=retry_at + timedelta(seconds=1),
    )
    assert failed.status == "failed"
    assert await lock_count(analysis_db) == 0


@pytest.mark.asyncio
async def test_replacement_activity_takes_over_run_and_fences_old_owner(
    analysis_db,
) -> None:
    _, command = await create_job(analysis_db, max_attempts=1)
    await analysis_db.repository.claim_run(
        command.id, command.run_id, 1, "lost-attempt", NOW, timedelta(seconds=30)
    )
    assert (
        await analysis_db.repository.claim_run(
            command.id, command.run_id, 2, "other-run", NOW, timedelta(seconds=30)
        )
        is None
    )
    taken = await analysis_db.repository.claim_run(
        command.id,
        command.run_id,
        1,
        "replacement",
        NOW + timedelta(seconds=1),
        timedelta(seconds=30),
    )
    # Takeover continues the same business attempt instead of consuming another.
    assert taken is not None
    assert (taken.attempt, taken.lease_owner, taken.stage) == (
        1,
        "replacement",
        "preparing",
    )
    assert not await analysis_db.repository.heartbeat(
        command.id,
        "lost-attempt",
        1,
        stage="preparing",
        progress=10,
        now=NOW + timedelta(seconds=2),
        lease_for=timedelta(seconds=30),
    )
    failed = await analysis_db.repository.fail_run(
        command.id,
        command.run_id,
        error_code="worker_lost",
        now=NOW + timedelta(seconds=3),
    )
    assert failed is not None
    assert (failed.status, failed.error_code) == ("failed", "worker_lost")
    assert await lock_count(analysis_db) == 0
    again = await analysis_db.repository.fail_run(
        command.id, command.run_id, error_code="worker_lost", now=NOW
    )
    assert again is not None and again.finished_at == failed.finished_at


@pytest.mark.asyncio
async def test_step_journal_replays_results_and_reports_unknown_outcomes(
    analysis_db,
) -> None:
    _, command = await create_job(analysis_db)
    journal = analysis_db.repository
    run_id = command.run_id
    digest = "d" * 64

    first = await journal.begin_step(run_id, "chunk-000", digest, now=NOW)
    assert first.status is AnalysisStepStatus.NEW
    await journal.complete_step(run_id, "chunk-000", {"scenes": [1]}, now=NOW)
    replay = await journal.begin_step(run_id, "chunk-000", digest, now=NOW)
    assert (replay.status, replay.payload) == (
        AnalysisStepStatus.REPLAY,
        {"scenes": [1]},
    )
    # A completed result for different input is simply recomputed.
    changed = await journal.begin_step(run_id, "chunk-000", "e" * 64, now=NOW)
    assert changed.status is AnalysisStepStatus.NEW

    await journal.begin_step(run_id, "chunk-001", digest, now=NOW)
    assert not await journal.has_started_step(uuid4())
    assert await journal.has_started_step(run_id)
    unknown = await journal.begin_step(run_id, "chunk-001", digest, now=NOW)
    assert unknown.status is AnalysisStepStatus.UNKNOWN
    await journal.abandon_step(run_id, "chunk-001")
    retried = await journal.begin_step(run_id, "chunk-001", digest, now=NOW)
    assert retried.status is AnalysisStepStatus.NEW

    await journal.purge_steps(run_id)
    async with analysis_db.sessions() as session:
        remaining = await session.scalar(
            select(func.count()).select_from(AnalysisStepResultRow)
        )
    assert remaining == 0
