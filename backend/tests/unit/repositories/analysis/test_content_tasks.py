from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.integrations.analysis_skill_catalog import BuiltinAnalysisSkillCatalog
from app.models import AnalysisJobRow, AnalysisRunRow, OutboxEventRow
from app.repositories.history_records import SqlAlchemyHistoryRecordRepository
from app.schemas.history_records import HistoryRecordPageResponse
from app.services.analysis.create_content_analysis import CreateContentAnalysis
from app.services.analysis.errors import AnalysisApplicationError
from app.services.analysis.get_analysis import GetAnalysis
from app.services.analysis_execution.errors import (
    AnalysisExecutionError,
    AnalysisOwnershipLost,
)
from app.services.analysis_execution.models import AnalysisStepStatus
from app.services.downloads.fingerprints import HmacRequestFingerprinter
from app.services.history_records import HistoryRecordFilters, HistoryRecordKind
from sqlalchemy import func, select, update
from tests.unit.workers.analysis.test_content_execution import source

NOW = datetime.now(UTC)
OWNER = "a" * 64


def creator(db):
    return CreateContentAnalysis(
        repository=db.repository,
        fingerprinter=HmacRequestFingerprinter(b"content-test-secret-32-bytes"),
        skill_catalog=BuiltinAnalysisSkillCatalog(),
        now=lambda: NOW,
        new_id=uuid4,
        enabled=True,
    )


async def claim(db):
    view = await creator(db)(source(), "zh-CN", OWNER, str(uuid4()))
    job = await db.repository.claim_run(
        view.id, view.run_id, view.run_no, "owner", NOW, timedelta(minutes=5)
    )
    assert job is not None
    return job


async def test_text_admission_is_atomic_idempotent_and_owner_scoped(analysis_db):
    create = creator(analysis_db)
    key = str(uuid4())
    first = await create(source(), "zh-CN", OWNER, key)
    replay = await create(source(), "zh-CN", OWNER, key)
    assert first.id == replay.id
    with pytest.raises(AnalysisApplicationError):
        await create(source("post"), "zh-CN", OWNER, key)
    with pytest.raises(AnalysisApplicationError):
        await GetAnalysis(analysis_db.repository)(first.id, "b" * 64)
    stored = await analysis_db.repository.get_job(first.id)
    assert stored.content_source == source()
    async with analysis_db.sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(OutboxEventRow)) == 1
        )
    history = await SqlAlchemyHistoryRecordRepository(analysis_db.sessions).history(
        OWNER, before=None, limit=10
    )
    assert history.items[0].record_type is HistoryRecordKind.CONTENT_CREATION
    encoded = HistoryRecordPageResponse.from_page(history).model_dump_json()
    assert "content_creation" in encoded and "owner_hash" not in encoded
    detail = await SqlAlchemyHistoryRecordRepository(analysis_db.sessions).history(
        OWNER, before=None, limit=10, filters=HistoryRecordFilters(analysis_id=first.id)
    )
    assert len(detail.items) == 1 and detail.items[0].id == first.id
    unavailable = await SqlAlchemyHistoryRecordRepository(analysis_db.sessions).history(
        "b" * 64,
        before=None,
        limit=10,
        filters=HistoryRecordFilters(analysis_id=first.id),
    )
    assert not unavailable.items


async def test_budget_binding_and_known_call_replay_are_durable(analysis_db):
    db = analysis_db
    job = await claim(db)
    bound = dict(owner="owner", attempt=job.attempt, now=NOW)
    binding = {
        "max_model_calls": 2,
        "source": job.input_sha256,
        "provider": "controlled",
    }
    await db.repository.bind_execution(
        job.run_id, binding, deadline=NOW + timedelta(minutes=2), **bound
    )
    await db.repository.begin_step(job.run_id, "draft", "a" * 64, **bound)
    await db.repository.complete_step(job.run_id, "draft", {"body": "原稿"}, **bound)
    for _ in range(2):
        value = await db.repository.begin_step(job.run_id, "draft", "a" * 64, **bound)
        assert value.status is AnalysisStepStatus.REPLAY
    await db.repository.begin_step(job.run_id, "review", "b" * 64, **bound)
    with pytest.raises(AnalysisExecutionError, match="analysis_resource_limit"):
        await db.repository.begin_step(job.run_id, "third", "c" * 64, **bound)
    with pytest.raises(AnalysisExecutionError, match="configuration_changed"):
        await db.repository.bind_execution(
            job.run_id,
            {**binding, "provider": "changed"},
            deadline=NOW + timedelta(minutes=10),
            **bound,
        )
    await db.repository.bind_execution(
        job.run_id, binding, deadline=NOW + timedelta(minutes=10), **bound
    )
    async with db.sessions() as session:
        run = await session.get(AnalysisRunRow, job.run_id)
        assert run.model_calls_used == 2
        assert run.execution_deadline == NOW + timedelta(minutes=2)


@pytest.mark.parametrize("change", ["cancel", "owner", "expired"])
async def test_late_results_cannot_overwrite_after_ownership_loss(analysis_db, change):
    db = analysis_db
    job = await claim(db)
    bound = dict(owner="owner", attempt=job.attempt, now=NOW)
    await db.repository.begin_step(job.run_id, "draft", "a" * 64, **bound)
    changes = {
        "cancel": {"cancel_requested_at": NOW},
        "owner": {"lease_owner": "replacement"},
        "expired": {"lease_expires_at": NOW},
    }[change]
    async with db.sessions() as session, session.begin():
        await session.execute(
            update(AnalysisJobRow).where(AnalysisJobRow.id == job.id).values(**changes)
        )
    with pytest.raises(AnalysisOwnershipLost):
        await db.repository.complete_step(job.run_id, "draft", {"late": True}, **bound)


async def test_deadline_does_not_refresh_after_restart(analysis_db):
    db = analysis_db
    job = await claim(db)
    bound = dict(owner="owner", attempt=job.attempt, now=NOW)
    binding = {"max_model_calls": 4}
    await db.repository.bind_execution(
        job.run_id, binding, deadline=NOW + timedelta(seconds=1), **bound
    )
    with pytest.raises(AnalysisExecutionError, match="resource_limit"):
        await db.repository.begin_step(
            job.run_id,
            "draft",
            "a" * 64,
            **{**bound, "now": NOW + timedelta(seconds=2)},
        )
