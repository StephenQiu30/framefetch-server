from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from app.models import (
    AnalysisArtifactLockRow,
    AnalysisReportArtifactRow,
    AnalysisResultRow,
    OutboxEventRow,
)
from app.repositories.analysis.report_repository import (
    ReportObject,
    SqlAlchemyAnalysisReportRepository,
)
from app.services.analysis.errors import PersistenceConflict
from app.services.analysis.models import AnalysisPublish
from app.services.analysis.rules.enums import AnalysisResultContract
from app.services.analysis.rules.result_models import AnalysisMedia
from app.services.analysis.rules.video_article_parser import parse_video_article_result
from sqlalchemy import func, select, update
from tests.unit.repositories.analysis.factories import (
    analysis_command,
    analysis_result,
    seed_artifact,
)
from tests.unit.services.analysis.rules.test_video_article import article_payload

NOW = datetime(2026, 8, 6, 8, tzinfo=UTC)


async def validating_job(
    analysis_db,
    *,
    result_contract: AnalysisResultContract = (
        AnalysisResultContract.VIDEO_VISUAL_ANALYSIS
    ),
):
    source = await seed_artifact(analysis_db.sessions, NOW)
    command = replace(analysis_command(source), result_contract=result_contract)
    await analysis_db.repository.create_job_and_enqueue(command, now=NOW)
    current = await analysis_db.repository.claim_run(
        command.id,
        command.run_id,
        1,
        "worker-a",
        NOW,
        timedelta(seconds=30),
    )
    assert current is not None
    for offset, stage, progress in (
        (1, "analyzing", 70),
        (2, "validating", 90),
    ):
        assert await analysis_db.repository.heartbeat(
            command.id,
            "worker-a",
            1,
            stage=stage,
            progress=progress,
            now=NOW + timedelta(seconds=offset),
            lease_for=timedelta(seconds=30),
        )
    job = await analysis_db.repository.get_job(command.id)
    assert job is not None
    return command, job


async def row_count(analysis_db, model: type[object]) -> int:
    async with analysis_db.sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


@pytest.mark.asyncio
async def test_result_and_success_publish_atomically_without_transcript(
    analysis_db,
) -> None:
    command, job = await validating_job(analysis_db)
    publish = AnalysisPublish(
        job_id=command.id,
        run_id=command.run_id,
        result=analysis_result(),
        lease_owner="worker-a",
        expected_version=job.version,
        provider="codex",
        model="controlled-model",
        cli_version="codex-cli controlled",
        now=NOW + timedelta(seconds=3),
    )

    succeeded = await analysis_db.repository.publish_result(publish)

    assert (succeeded.status, succeeded.stage, succeeded.progress) == (
        "running",
        "publishing",
        95,
    )
    assert await row_count(analysis_db, AnalysisArtifactLockRow) == 1
    assert await row_count(analysis_db, AnalysisResultRow) == 1
    async with analysis_db.sessions() as session:
        row = await session.scalar(
            select(AnalysisResultRow).where(AnalysisResultRow.job_id == command.id)
        )
        assert row is not None
        assert (row.provider, row.model) == (
            "codex",
            "controlled-model",
        )
        assert set(row.result_json) == {
            "language",
            "title",
            "summary",
            "media",
            "shot_count",
            "shots",
            "scenes",
            "highlights",
            "assets",
            "production_advice",
            "kind",
        }
        assert row.result_json["kind"] == "video_visual_analysis"
        serialized = json.dumps(row.result_json, ensure_ascii=False).lower()
        assert "transcript" not in serialized
        assert "provider_response" not in serialized
        assert row.status == "validated"
        assert len(row.content_sha256) == 64
    assert await analysis_db.repository.get_result(command.id) == publish.result

    replay = await analysis_db.repository.publish_result(publish)
    assert replay.stage == "publishing"
    assert await row_count(analysis_db, AnalysisResultRow) == 1

    changed = replace(analysis_result(), title="不同输出")
    with pytest.raises(PersistenceConflict):
        await analysis_db.repository.publish_result(replace(publish, result=changed))


@pytest.mark.asyncio
async def test_video_article_result_can_be_published(analysis_db) -> None:
    command, job = await validating_job(
        analysis_db, result_contract=AnalysisResultContract.VIDEO_ARTICLE
    )
    article = parse_video_article_result(
        article_payload(),
        AnalysisMedia(duration_ms=3_000, container="mp4", size_bytes=1_024),
        expected_language="zh-CN",
    )

    publishing = await analysis_db.repository.publish_result(
        AnalysisPublish(
            job_id=command.id,
            run_id=command.run_id,
            result=article,
            lease_owner="worker-a",
            expected_version=job.version,
            provider="codex",
            model="controlled-model",
            cli_version="codex-cli controlled",
            now=NOW + timedelta(seconds=3),
        )
    )

    assert (publishing.status, publishing.stage, publishing.progress) == (
        "running",
        "publishing",
        95,
    )
    stored = await analysis_db.repository.get_result(command.id)
    assert stored == article


@pytest.mark.asyncio
async def test_publish_requires_matching_validating_lease_and_version(
    analysis_db,
) -> None:
    command, job = await validating_job(analysis_db)
    valid = AnalysisPublish(
        job_id=command.id,
        run_id=command.run_id,
        result=analysis_result(),
        lease_owner="worker-a",
        expected_version=job.version,
        provider="codex",
        model="controlled-model",
        cli_version="codex-cli controlled",
        now=NOW + timedelta(seconds=3),
    )

    for invalid in (
        replace(valid, lease_owner="worker-b"),
        replace(valid, expected_version=job.version - 1),
        replace(valid, now=NOW + timedelta(minutes=1)),
    ):
        with pytest.raises(PersistenceConflict):
            await analysis_db.repository.publish_result(invalid)
        assert await row_count(analysis_db, AnalysisResultRow) == 0


@pytest.mark.asyncio
async def test_report_finalization_atomically_switches_current_report(
    analysis_db,
) -> None:
    command, job = await validating_job(analysis_db)
    publishing = await analysis_db.repository.publish_result(
        AnalysisPublish(
            job_id=command.id,
            run_id=command.run_id,
            result=analysis_result(),
            lease_owner="worker-a",
            expected_version=job.version,
            provider="codex",
            model="controlled-model",
            cli_version="codex-cli controlled",
            now=NOW + timedelta(seconds=3),
        )
    )
    repository = SqlAlchemyAnalysisReportRepository(analysis_db.sessions)
    report = await repository.get_latest_report(command.id)
    assert report is not None and report.status == "validated"
    publication = await repository.claim(
        report_id=report.id,
        job_id=command.id,
        run_id=command.run_id,
        expected_version=publishing.version,
        worker_id="report-a",
        now=NOW + timedelta(seconds=4),
        lease_for=timedelta(minutes=1),
    )
    assert publication is not None
    objects = tuple(
        ReportObject(
            format=report_format,
            bucket="video-artifacts",
            object_key=f"analyses/{command.id}/{report.id}/report.{suffix}",
            content_type=content_type,
            size_bytes=12,
            sha256=letter * 64,
        )
        for report_format, suffix, content_type, letter in (
            ("markdown", "md", "text/markdown; charset=utf-8", "a"),
            (
                "docx",
                "docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "b",
            ),
        )
    )
    await repository.complete(
        publication, "report-a", objects, NOW + timedelta(seconds=5)
    )

    completed = await repository.get_job(command.id)
    assert completed is not None
    assert (completed.status, completed.progress, completed.current_report_id) == (
        "succeeded",
        100,
        report.id,
    )
    assert await row_count(analysis_db, AnalysisArtifactLockRow) == 0
    assert (await repository.get_current_report_file(command.id, "docx")) is not None
    async with analysis_db.sessions() as session:
        report_artifacts = tuple(
            (
                await session.scalars(
                    select(AnalysisReportArtifactRow).where(
                        AnalysisReportArtifactRow.report_id == report.id
                    )
                )
            ).all()
        )
    assert {item.status for item in report_artifacts} == {"available"}

    assert await analysis_db.repository.delete_job(
        command.id, command.owner_hash, NOW + timedelta(seconds=6)
    )
    assert await analysis_db.repository.get_job(command.id) is None
    deleted_keys: list[str] = []

    async def delete_object(key: str) -> None:
        deleted_keys.append(key)

    purged = await repository.purge_report_artifacts(
        NOW + timedelta(seconds=7), delete_object, limit=10
    )
    assert (purged.deleted, purged.failed) == (2, 0)
    assert set(deleted_keys) == {item.object_key for item in objects}
    deleted_report = await repository.get_latest_report(command.id)
    assert deleted_report is not None and deleted_report.status == "deleted"
    assert deleted_report.artifacts == ()
    assert await repository.get_current_report_file(command.id, "docx") is None


@pytest.mark.asyncio
async def test_failed_report_publication_is_reenqueued_once(analysis_db) -> None:
    command, job = await validating_job(analysis_db)
    publishing = await analysis_db.repository.publish_result(
        AnalysisPublish(
            job_id=command.id,
            run_id=command.run_id,
            result=analysis_result(),
            lease_owner="worker-a",
            expected_version=job.version,
            provider="codex",
            model="controlled-model",
            cli_version="codex-cli controlled",
            now=NOW + timedelta(seconds=3),
        )
    )
    repository = SqlAlchemyAnalysisReportRepository(analysis_db.sessions)
    report = await repository.get_latest_report(command.id)
    assert report is not None
    async with analysis_db.sessions() as session, session.begin():
        await session.execute(
            update(OutboxEventRow)
            .where(OutboxEventRow.aggregate_id == report.id)
            .values(published_at=NOW + timedelta(seconds=4))
        )
    publication = await repository.claim(
        report_id=report.id,
        job_id=command.id,
        run_id=command.run_id,
        expected_version=publishing.version,
        worker_id="report-a",
        now=NOW + timedelta(seconds=5),
        lease_for=timedelta(minutes=1),
    )
    assert publication is not None
    await repository.fail(
        report.id, "report-a", "controlled failure", NOW + timedelta(seconds=6)
    )

    assert await repository.recover_pending(NOW + timedelta(seconds=7)) == (report.id,)
    assert await repository.recover_pending(NOW + timedelta(seconds=8)) == ()
    async with analysis_db.sessions() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(OutboxEventRow)
            .where(OutboxEventRow.aggregate_id == report.id)
        )
    assert count == 2
