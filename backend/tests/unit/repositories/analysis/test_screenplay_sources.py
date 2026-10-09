from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models import AnalysisArtifactLockRow, AnalysisDocumentLockRow, OutboxEventRow
from app.repositories.analysis.execution import AnalysisExecutionPersistence
from app.services.analysis.errors import PersistenceConflict, PersistenceNotFound
from app.services.analysis.models import AnalysisRetry
from app.services.analysis_execution.errors import AnalysisSourceUnavailable
from sqlalchemy import func, select
from tests.unit.repositories.analysis.factories import OWNER
from tests.unit.repositories.analysis.screenplay_factories import (
    screenplay_command,
    seed_screenplay,
)

NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)


async def count_rows(analysis_db, model: type[object]) -> int:
    async with analysis_db.sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


@pytest.mark.asyncio
async def test_screenplay_projection_creation_and_lock_are_owner_scoped(
    analysis_db,
) -> None:
    source = await seed_screenplay(analysis_db.sessions, NOW)
    projected = await analysis_db.repository.get_document_for_analysis(
        source.document_id
    )
    assert projected is not None
    assert (
        projected.owner_hash,
        projected.status,
        projected.text_sha256,
        projected.normalized_status,
        projected.normalized_sha256,
    ) == (OWNER, "ready", source.sha256, "ready", source.sha256)
    assert await analysis_db.repository.get_document_for_analysis(uuid4()) is None
    execution_source = await analysis_db.repository.get_screenplay_source(
        source.document_id, NOW
    )
    assert execution_source is not None
    assert (
        execution_source.document_id,
        execution_source.owner_hash,
        execution_source.sha256,
        execution_source.character_count,
        execution_source.scenes[0].id,
    ) == (source.document_id, OWNER, source.sha256, 64, "scene-0001")

    command = screenplay_command(source)
    saved = await analysis_db.repository.create_job_and_enqueue(command, now=NOW)

    assert saved.created is True
    assert saved.job.artifact_id is None
    assert saved.job.document_id == source.document_id
    assert (saved.job.input_kind, saved.job.result_contract) == (
        "screenplay",
        "screenplay-analysis",
    )
    assert await count_rows(analysis_db, AnalysisArtifactLockRow) == 0
    assert await count_rows(analysis_db, AnalysisDocumentLockRow) == 1
    assert await count_rows(analysis_db, OutboxEventRow) == 1


@pytest.mark.asyncio
async def test_worker_screenplay_projection_revalidates_job_hash(analysis_db) -> None:
    source = await seed_screenplay(analysis_db.sessions, NOW)
    saved = await analysis_db.repository.create_job_and_enqueue(
        screenplay_command(source), now=NOW
    )
    persistence = AnalysisExecutionPersistence(
        analysis_db.repository,
        downloads=object(),  # type: ignore[arg-type]
    )

    projected = await persistence.get_screenplay_source(saved.job, NOW)

    assert projected.document_id == source.document_id
    assert projected.sha256 == source.sha256
    with pytest.raises(AnalysisSourceUnavailable):
        await persistence.get_screenplay_source(
            replace(saved.job, input_sha256="0" * 64), NOW
        )


@pytest.mark.asyncio
async def test_latest_screenplay_analysis_is_owner_and_document_scoped(
    analysis_db,
) -> None:
    source = await seed_screenplay(analysis_db.sessions, NOW)
    other = await seed_screenplay(analysis_db.sessions, NOW)
    first = screenplay_command(source)
    second = replace(
        screenplay_command(source),
        idempotency_key="analysis-latest",
        request_fingerprint="b" * 64,
    )
    other_command = screenplay_command(other)
    await analysis_db.repository.create_job_and_enqueue(first, now=NOW)
    await analysis_db.repository.create_job_and_enqueue(
        second, now=NOW + timedelta(seconds=1)
    )
    await analysis_db.repository.create_job_and_enqueue(
        other_command, now=NOW + timedelta(seconds=2)
    )

    latest = await analysis_db.repository.get_latest_job_for_document(
        source.document_id, OWNER
    )

    assert latest is not None and latest.id == second.id
    assert (
        await analysis_db.repository.get_latest_job_for_document(
            source.document_id, "b" * 64
        )
        is None
    )
    assert (
        await analysis_db.repository.get_latest_job_for_document(uuid4(), OWNER) is None
    )


@pytest.mark.asyncio
async def test_screenplay_creation_revalidates_state_owner_and_sha(
    analysis_db,
) -> None:
    failed = await seed_screenplay(analysis_db.sessions, NOW, status="failed")
    foreign = await seed_screenplay(analysis_db.sessions, NOW, owner_hash="b" * 64)
    missing_text = await seed_screenplay(
        analysis_db.sessions, NOW, normalized_status=None
    )
    deleting_text = await seed_screenplay(
        analysis_db.sessions, NOW, normalized_status="deleting"
    )

    for command in (
        screenplay_command(failed),
        replace(screenplay_command(foreign), owner_hash=OWNER),
        screenplay_command(missing_text),
        screenplay_command(deleting_text),
    ):
        with pytest.raises(PersistenceNotFound):
            await analysis_db.repository.create_job_and_enqueue(command, now=NOW)

    valid = await seed_screenplay(analysis_db.sessions, NOW)
    with pytest.raises(PersistenceConflict):
        await analysis_db.repository.create_job_and_enqueue(
            replace(screenplay_command(valid), input_sha256="0" * 64), now=NOW
        )


@pytest.mark.asyncio
async def test_screenplay_retry_recreates_and_terminal_paths_release_lock(
    analysis_db,
) -> None:
    source = await seed_screenplay(analysis_db.sessions, NOW)
    command = screenplay_command(source)
    await analysis_db.repository.create_job_and_enqueue(command, now=NOW)
    await analysis_db.repository.claim_run(
        command.id,
        command.run_id,
        1,
        "worker-a",
        NOW,
        timedelta(seconds=30),
    )
    failed = await analysis_db.repository.complete_failure(
        command.id,
        "worker-a",
        1,
        error_code="analysis_cli_failed",
        error_message="controlled",
        retryable=False,
        now=NOW + timedelta(seconds=1),
    )
    assert failed.status == "failed"
    assert await count_rows(analysis_db, AnalysisDocumentLockRow) == 0

    retry = AnalysisRetry(
        job_id=command.id,
        run_id=uuid4(),
        owner_hash=command.owner_hash,
        idempotency_key="screenplay-retry",
        trigger="manual_retry",
        outbox_event_id=uuid4(),
        max_attempts=3,
    )
    retried = await analysis_db.repository.retry_job_and_enqueue(
        retry, now=NOW + timedelta(seconds=30)
    )
    assert retried.created is True
    assert await count_rows(analysis_db, AnalysisDocumentLockRow) == 1
    cancelled = await analysis_db.repository.cancel_job(
        command.id, command.owner_hash, NOW + timedelta(seconds=31)
    )
    assert cancelled.status == "cancelled"
    assert await count_rows(analysis_db, AnalysisDocumentLockRow) == 0
