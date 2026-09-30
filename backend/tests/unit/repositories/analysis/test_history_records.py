from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models import AnalysisJobRow, ArtifactRow, DocumentRow
from app.models.download_intent import DownloadIntentRow
from app.repositories.history_records import SqlAlchemyHistoryRecordRepository
from app.schemas.history_records import HistoryRecordPageResponse
from app.schemas.resolution import PROVIDER_FAILURE
from app.services.history_records import (
    HistoryRecordFilters,
    HistoryRecordKind,
    HistoryStatusGroup,
)
from app.services.provider_failures import ProviderFailure
from sqlalchemy import update
from tests.unit.repositories.analysis.factories import (
    OWNER,
    analysis_command,
    seed_artifact,
)
from tests.unit.repositories.analysis.screenplay_factories import (
    screenplay_command,
    seed_screenplay,
)

NOW = datetime(2026, 9, 24, tzinfo=UTC)


async def seed(db):
    video = await seed_artifact(db.sessions, NOW)
    doc = await seed_screenplay(db.sessions, NOW)
    video_job = await db.repository.create_job_and_enqueue(
        analysis_command(video), now=NOW
    )
    # Deliberately same UUID as the document: cursor needs its type tiebreaker.
    script_job = await db.repository.create_job_and_enqueue(
        replace(screenplay_command(doc), id=doc.document_id), now=NOW
    )
    async with db.sessions() as session, session.begin():
        session.add(
            DownloadIntentRow(
                id=uuid4(),
                owner_hash=OWNER,
                idempotency_key=str(uuid4()),
                request_fingerprint="f" * 64,
                url_ciphertext=b"cipher",
                url_nonce=b"nonce",
                url_key_id="test",
                access_policy="public",
                deadline=NOW + timedelta(hours=1),
                created_at=NOW,
                updated_at=NOW,
            )
        )
    return video, doc, video_job.job, script_job.job


@pytest.mark.asyncio
async def test_four_types_stable_cursor_and_owner(analysis_db):
    await seed(analysis_db)
    await seed_screenplay(analysis_db.sessions, NOW, owner_hash="b" * 64)
    repo = SqlAlchemyHistoryRecordRepository(analysis_db.sessions)
    all_records = await repo.history(OWNER, before=None, limit=20)
    assert {r.record_type for r in all_records.items} == set(HistoryRecordKind)
    observed = []
    cursor = None
    for _ in range(5):
        page = await repo.history(OWNER, before=cursor, limit=1)
        observed.extend((r.record_type, r.id) for r in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert observed == [(r.record_type, r.id) for r in all_records.items]
    assert len(set(observed)) == 4
    encoded = HistoryRecordPageResponse.from_page(all_records).model_dump_json()
    assert (
        "cipher" not in encoded
        and "owner_hash" not in encoded
        and "object_key" not in encoded
    )
    assert len((await repo.history("b" * 64, before=None, limit=20)).items) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,action", [("retry_wait", "wait"), ("failed", "refresh_result")]
)
async def test_parse_history_preserves_failure_phase_without_private_context(
    analysis_db, status, action
):
    await seed(analysis_db)
    failure = ProviderFailure.for_code("pot_provider_unavailable").with_context(
        "yt-dlp-session", "private-context"
    )
    async with analysis_db.sessions() as session, session.begin():
        await session.execute(
            update(DownloadIntentRow)
            .where(DownloadIntentRow.owner_hash == OWNER)
            .values(
                status=status,
                reason_code="inspection_failed",
                latest_failure=PROVIDER_FAILURE.dump_python(failure, mode="json"),
                retry_at=NOW + timedelta(seconds=15)
                if status == "retry_wait"
                else None,
            )
        )
    records = await SqlAlchemyHistoryRecordRepository(analysis_db.sessions).history(
        OWNER, before=None, limit=20
    )
    response = HistoryRecordPageResponse.from_page(records)
    parsed = next(item for item in response.items if item.record_type == "parse")
    assert parsed.phase == failure.phase
    assert parsed.failure.code == "pot_provider_unavailable"
    assert parsed.failure.failure_class == "token_unavailable"
    assert parsed.next_action == action
    assert parsed.status_group == ("processing" if status == "retry_wait" else "failed")
    encoded = response.model_dump_json()
    assert "private-context" not in encoded
    assert "yt-dlp-session" not in encoded


@pytest.mark.asyncio
async def test_filters_apply_before_pagination_and_literal_search(analysis_db):
    _, doc, _, script = await seed(analysis_db)
    repo = SqlAlchemyHistoryRecordRepository(analysis_db.sessions)
    filters = HistoryRecordFilters(
        document_id=doc.document_id,
        record_types=(HistoryRecordKind.SCREENPLAY_ANALYSIS,),
        status_group=HistoryStatusGroup.PROCESSING,
        created_from=NOW,
        created_to=NOW + timedelta(seconds=1),
        skill_id="screenplay-analysis",
    )
    page = await repo.history(OWNER, before=None, limit=1, filters=filters)
    assert [r.id for r in page.items] == [script.id]
    assert page.next_cursor is None
    assert not (
        await repo.history(
            OWNER, before=None, limit=20, filters=replace(filters, q="%")
        )
    ).items
    assert not (
        await repo.history(
            OWNER, before=None, limit=20, filters=replace(filters, created_to=NOW)
        )
    ).items


@pytest.mark.asyncio
async def test_source_deletion_preserves_analysis_and_soft_delete_hides_it(analysis_db):
    video, doc, _, script = await seed(analysis_db)
    repo = SqlAlchemyHistoryRecordRepository(analysis_db.sessions)
    async with analysis_db.sessions() as session, session.begin():
        await session.execute(
            update(DocumentRow)
            .where(DocumentRow.id == doc.document_id)
            .values(deleted_at=NOW)
        )
        await session.execute(
            update(ArtifactRow)
            .where(ArtifactRow.id == video.artifact_id)
            .values(deleted_at=NOW)
        )
    page = await repo.history(OWNER, before=None, limit=20)
    assert len(page.items) == 3
    analyses = [r for r in page.items if r.skill_id]
    assert all(r.source_availability == "unavailable" for r in analyses)
    async with analysis_db.sessions() as session, session.begin():
        await session.execute(
            update(AnalysisJobRow)
            .where(AnalysisJobRow.id == script.id)
            .values(deleted_at=NOW)
        )
    assert len((await repo.history(OWNER, before=None, limit=20)).items) == 2
    assert not await repo.runs(OWNER, script.id, before_run_no=None, limit=20)


@pytest.mark.asyncio
async def test_runs_are_owner_scoped_and_not_list_rows(analysis_db):
    _, _, _, script = await seed(analysis_db)
    repo = SqlAlchemyHistoryRecordRepository(analysis_db.sessions)
    runs = await repo.runs(OWNER, script.id, before_run_no=None, limit=20)
    assert [(r.run_no, r.trigger) for r in runs] == [(1, "initial")]
    assert not await repo.runs("b" * 64, script.id, before_run_no=None, limit=20)
    assert not await repo.runs(OWNER, script.id, before_run_no=1, limit=20)
