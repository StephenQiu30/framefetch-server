from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from app.models import AnalysisJobRow, AnalysisRunRow, DocumentRow
from app.services.analysis.rules.enums import AnalysisInputKind
from tests.unit.repositories.analysis.conftest import AnalysisDatabase

START = datetime(2026, 8, 4, tzinfo=UTC)
END = datetime(2026, 8, 10, 12, 30, tzinfo=UTC)


async def add_job(
    database: AnalysisDatabase,
    *,
    input_kind: str = "video",
    deleted: bool = False,
) -> UUID:
    job_id = uuid4()
    document_id = uuid4() if input_kind == "screenplay" else None
    async with database.sessions() as session, session.begin():
        if document_id is not None:
            session.add(
                DocumentRow(
                    id=document_id,
                    owner_hash="a" * 64,
                    idempotency_key=str(document_id),
                    request_fingerprint="b" * 64,
                    title="统计测试文档",
                    original_filename="test.txt",
                    source_format="txt",
                    content_type="text/plain",
                    declared_size_bytes=1,
                    declared_sha256="c" * 64,
                    rights_statement_version="test",
                )
            )
            await session.flush()
        # The job predates the window and its current status differs from its
        # historical runs: analytics must use run.created_at and run.status.
        session.add(
            AnalysisJobRow(
                id=job_id,
                input_kind=input_kind,
                result_contract=(
                    "screenplay-analysis"
                    if document_id is not None
                    else "video-visual-analysis"
                ),
                document_id=document_id,
                artifact_id=uuid4() if document_id is None else None,
                owner_hash="a" * 64,
                idempotency_key=str(job_id),
                request_fingerprint="d" * 64,
                input_sha256="e" * 64,
                skill_id="test-skill",
                skill_instructions="test",
                skill_instructions_sha256="f" * 64,
                output_language="zh-CN",
                status="queued",
                active_run_id=uuid4(),
                created_at=START - timedelta(days=1),
                updated_at=END,
                deleted_at=END if deleted else None,
            )
        )
    return job_id


async def add_run(
    database: AnalysisDatabase,
    job_id: UUID,
    *,
    run_no: int,
    status: str,
    created_at: datetime = START,
    trigger: str = "initial",
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> None:
    async with database.sessions() as session, session.begin():
        session.add(
            AnalysisRunRow(
                job_id=job_id,
                run_no=run_no,
                trigger=trigger,
                status=status,
                created_at=created_at,
                updated_at=END,
                started_at=started_at,
                finished_at=finished_at,
            )
        )


@pytest.mark.asyncio
async def test_analytics_counts_each_retained_run_including_soft_deleted_jobs(
    analysis_db: AnalysisDatabase,
) -> None:
    video = await add_job(analysis_db, deleted=True)
    await add_run(analysis_db, video, run_no=1, status="failed")
    await add_run(
        analysis_db, video, run_no=2, status="succeeded", trigger="manual_retry"
    )
    await add_run(
        analysis_db, video, run_no=3, status="retry_wait", trigger="manual_rerun"
    )
    active = await add_job(analysis_db)
    await add_run(analysis_db, active, run_no=1, status="running")
    await add_run(
        analysis_db, active, run_no=2, status="queued", trigger="manual_retry"
    )
    screenplay = await add_job(analysis_db, input_kind="screenplay")
    await add_run(analysis_db, screenplay, run_no=1, status="cancelled")

    analytics = await analysis_db.repository.get_analysis_analytics(
        start=START, end=END
    )

    assert analytics.summary.total == 6
    assert (
        analytics.summary.succeeded,
        analytics.summary.failed,
        analytics.summary.cancelled,
        analytics.summary.active,
    ) == (1, 1, 1, 3)
    assert [(item.input_kind, item.total) for item in analytics.inputs] == [
        (AnalysisInputKind.SCREENPLAY, 1),
        (AnalysisInputKind.VIDEO, 5),
    ]
    assert len(analytics.daily) == 1
    assert analytics.daily[0].date == START.date()
    assert analytics.daily[0].total == 6
    assert analytics.daily[0].active == 3


@pytest.mark.asyncio
async def test_analytics_cohort_includes_exact_start_and_end_not_adjacent_runs(
    analysis_db: AnalysisDatabase,
) -> None:
    job = await add_job(analysis_db)
    times = (
        START - timedelta(microseconds=1),
        START,
        END,
        END + timedelta(microseconds=1),
    )
    for number, current in enumerate(times, start=1):
        await add_run(
            analysis_db, job, run_no=number, status="queued", created_at=current
        )

    analytics = await analysis_db.repository.get_analysis_analytics(
        start=START, end=END
    )

    assert analytics.summary.total == 2
    assert [(item.date, item.total) for item in analytics.daily] == [
        (START.date(), 1),
        (END.date(), 1),
    ]


@pytest.mark.asyncio
async def test_analytics_groups_by_utc_date_not_input_timezone(
    analysis_db: AnalysisDatabase,
) -> None:
    job = await add_job(analysis_db)
    local = datetime(2026, 8, 10, 0, 30, tzinfo=timezone(timedelta(hours=8)))
    await add_run(analysis_db, job, run_no=1, status="running", created_at=local)

    analytics = await analysis_db.repository.get_analysis_analytics(
        start=START, end=END
    )

    assert analytics.daily[0].date == datetime(2026, 8, 9, tzinfo=UTC).date()
    assert analytics.daily[0].active == 1


@pytest.mark.asyncio
async def test_analytics_duration_uses_only_valid_terminal_samples(
    analysis_db: AnalysisDatabase,
) -> None:
    job = await add_job(analysis_db)
    cases = (
        ("succeeded", START, START + timedelta(seconds=60)),
        ("failed", START, START + timedelta(seconds=30)),
        ("cancelled", START, START),
        ("failed", None, START + timedelta(seconds=90)),
        ("failed", START, None),
        ("cancelled", START, START - timedelta(seconds=10)),
        ("running", START, START + timedelta(seconds=900)),
        ("retry_wait", START, START + timedelta(seconds=900)),
    )
    for number, (status, began, finished) in enumerate(cases, start=1):
        await add_run(
            analysis_db,
            job,
            run_no=number,
            status=status,
            started_at=began,
            finished_at=finished,
        )

    analytics = await analysis_db.repository.get_analysis_analytics(
        start=START, end=END
    )

    assert analytics.summary.total == 8
    assert analytics.summary.completed_duration_count == 3
    assert analytics.summary.average_duration_seconds == 30.0


@pytest.mark.asyncio
async def test_analytics_empty_cohort_has_no_measured_duration(
    analysis_db: AnalysisDatabase,
) -> None:
    analytics = await analysis_db.repository.get_analysis_analytics(
        start=START, end=END
    )

    assert analytics.summary.total == analytics.summary.completed_duration_count == 0
    assert analytics.summary.average_duration_seconds is None
    assert analytics.daily == analytics.inputs == ()


@pytest.mark.parametrize("end", [START, START - timedelta(seconds=1)])
@pytest.mark.asyncio
async def test_analytics_rejects_invalid_period(
    analysis_db: AnalysisDatabase, end: datetime
) -> None:
    with pytest.raises(ValueError, match="start must be before end"):
        await analysis_db.repository.get_analysis_analytics(start=START, end=end)
