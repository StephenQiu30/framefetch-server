from copy import deepcopy
from uuid import uuid4

import pytest
from app.integrations.analysis_report_docx import PythonDocxAnalysisReportRenderer
from app.integrations.object_storage import StoredObjectStat
from app.models import (
    AnalysisJobRow,
    AnalysisReportArtifactRow,
    AnalysisResultRow,
    AnalysisRunRow,
)
from app.repositories.analysis.execution import AnalysisExecutionPersistence
from app.repositories.analysis.report_repository import (
    SqlAlchemyAnalysisReportRepository,
)
from app.repositories.downloads.repository import SqlAlchemyDownloadRepository
from app.services.analysis.errors import PersistenceNotFound
from app.services.analysis_execution.content_executor import ContentExecutor
from app.services.analysis_execution.service import AnalysisExecution
from app.workers.report.message import ReportRequested
from app.workers.report.publisher import ReportPublisher
from sqlalchemy import select
from tests.unit.repositories.analysis.test_content_tasks import NOW, OWNER, creator
from tests.unit.workers.analysis.fakes import FakeLoader, settings
from tests.unit.workers.analysis.test_content_execution import (
    Analyzer,
    Resolver,
    draft,
    plan,
    review,
    source,
)


class Storage:
    def __init__(self):
        self.values = {}
        self.stats = {}

    async def stat(self, key):
        return self.stats.get(key)

    async def upload_bytes(self, key, content, media_type, digest):
        self.values[key] = content
        self.stats[key] = StoredObjectStat(len(content), digest, media_type)


async def publish(db, storage, job):
    reports = SqlAlchemyAnalysisReportRepository(db.sessions)
    async with db.sessions() as session:
        report = await session.scalar(
            select(AnalysisResultRow).where(AnalysisResultRow.run_id == job.run_id)
        )
    publisher = ReportPublisher(
        reports,
        storage,
        PythonDocxAnalysisReportRenderer(),
        bucket="private-test",
        worker_id="publisher",
        clock=lambda: NOW,
    )
    assert await publisher.execute(
        ReportRequested(
            job_id=job.id,
            run_id=job.run_id,
            report_id=report.id,
            version=job.version,
            renderer_version=report.renderer_version,
        )
    )
    return await db.repository.get_job(job.id)


async def completed(db, tmp_path):
    admitted = await creator(db)(source(), "zh-CN", OWNER, str(uuid4()))
    resolver = Resolver(Analyzer([plan(), draft(), review()]))
    persistence = AnalysisExecutionPersistence(
        db.repository, SqlAlchemyDownloadRepository(db.sessions)
    )
    execution = AnalysisExecution(
        repository=persistence,
        loader=FakeLoader(tmp_path / "unused"),
        resolver=resolver,
        content_executor=ContentExecutor(
            resolver=resolver, workspace_root=tmp_path / "content"
        ),
        clock=lambda: NOW,
        settings=settings(),
    )
    pending = await execution.execute(
        admitted.id, admitted.run_id, admitted.run_no, "worker"
    )
    storage = Storage()
    job = await publish(db, storage, pending)
    assert job.status == "succeeded"
    return job, storage


async def test_published_content_is_read_only_and_retains_its_formats(
    analysis_db, tmp_path
):
    job, storage = await completed(analysis_db, tmp_path)
    assert len(storage.values) == 2
    assert {key.rsplit(".", 1)[-1] for key in storage.values} == {"md", "docx"}
    assert not hasattr(analysis_db.repository, "revise_content")
    versions = await analysis_db.repository.content_versions(job.id, OWNER)
    assert [item.run_no for item in versions] == [1]
    assert versions[0].result.review_status == "passed"
    assert versions[0].result.review_history[-1].findings == ()


async def test_existing_manual_reports_remain_readable_without_a_write_use_case(
    analysis_db, tmp_path
):
    db = analysis_db
    job, storage = await completed(db, tmp_path)
    original_files = dict(storage.values)
    original = await db.repository.get_result(job.id)
    run_id, report_id = uuid4(), uuid4()
    # Seed a previously saved manual report; the retired writer is not used.
    async with db.sessions() as session, session.begin():
        old_run = await session.get(AnalysisRunRow, job.run_id)
        old_report = await session.get(AnalysisResultRow, job.current_report_id)
        run_fields = {
            column.name: deepcopy(getattr(old_run, column.name))
            for column in AnalysisRunRow.__table__.columns
        }
        run_fields.update(
            id=run_id,
            run_no=2,
            trigger="manual_edit",
            model_calls_used=0,
            provider="manual",
            model="none",
            cli_version="none",
        )
        session.add(AnalysisRunRow(**run_fields))
        await session.flush()
        report_fields = {
            column.name: deepcopy(getattr(old_report, column.name))
            for column in AnalysisResultRow.__table__.columns
        }
        result_json = report_fields["result_json"]
        result_json["review_status"] = "needs_review"
        result_json["evidence_index"] = []
        result_json["review_history"].append(
            {
                "needs_material": False,
                "findings": [
                    {
                        "block_id": "title",
                        "severity": "major",
                        "category": "fact",
                        "problem": "历史稿件经过人工改动",
                        "correction": "原自动审校结论不适用",
                    }
                ],
            }
        )
        report_fields.update(
            id=report_id,
            run_id=run_id,
            provider="manual",
            model="none",
            cli_version="none",
        )
        session.add(AnalysisResultRow(**report_fields))
        await session.flush()
        stored = await session.get(AnalysisJobRow, job.id)
        stored.active_run_id = run_id
        stored.current_run_no = 2
        stored.current_run_trigger = "manual_edit"
        stored.current_report_id = report_id
        artifacts = (
            await session.scalars(
                select(AnalysisReportArtifactRow).where(
                    AnalysisReportArtifactRow.report_id == job.current_report_id
                )
            )
        ).all()
        for artifact in artifacts:
            fields = {
                column.name: deepcopy(getattr(artifact, column.name))
                for column in AnalysisReportArtifactRow.__table__.columns
            }
            key = artifact.object_key.replace("/runs/1/", "/runs/2/").replace(
                str(job.current_report_id), str(report_id)
            )
            fields.update(id=uuid4(), report_id=report_id, object_key=key)
            session.add(AnalysisReportArtifactRow(**fields))
            storage.values[key] = storage.values[artifact.object_key]
    versions = await db.repository.content_versions(job.id, OWNER)
    assert [item.run_no for item in versions] == [2, 1]
    assert versions[1].result == original
    assert versions[0].result.review_status == "needs_review"
    assert versions[0].markdown == versions[1].markdown
    async with db.sessions() as session, session.begin():
        unpublished = await session.get(AnalysisResultRow, report_id)
        unpublished.status = "validated"
        unpublished.published_at = None
    assert [
        item.run_no for item in await db.repository.content_versions(job.id, OWNER)
    ] == [1]
    async with db.sessions() as session, session.begin():
        published = await session.get(AnalysisResultRow, report_id)
        published.status = "available"
        published.published_at = NOW
    current = await db.repository.get_latest_report(job.id)
    assert {item.format for item in current.artifacts} == {"markdown", "docx"}
    assert (await db.repository.get_result(job.id)).review_status == "needs_review"
    assert all(storage.values[key] == value for key, value in original_files.items())
    # Removing export files does not remove the retained report prose.
    async with db.sessions() as session, session.begin():
        reports = (
            await session.scalars(
                select(AnalysisResultRow).where(AnalysisResultRow.job_id == job.id)
            )
        ).all()
        for report in reports:
            report.status = "deleted"
        artifacts = (
            await session.scalars(
                select(AnalysisReportArtifactRow).where(
                    AnalysisReportArtifactRow.report_id.in_(
                        [job.current_report_id, report_id]
                    )
                )
            )
        ).all()
        for artifact in artifacts:
            artifact.status = "deleted"
            artifact.deleted_at = NOW
    assert [
        item.run_no for item in await db.repository.content_versions(job.id, OWNER)
    ] == [2, 1]
    assert (await db.repository.get_latest_report(job.id)).artifacts == ()
    with pytest.raises(PersistenceNotFound):
        await db.repository.content_versions(job.id, "b" * 64)
    async with db.sessions() as session, session.begin():
        stored = await session.get(AnalysisJobRow, job.id)
        stored.deleted_at = NOW
    with pytest.raises(PersistenceNotFound):
        await db.repository.content_versions(job.id, OWNER)


async def test_retired_format_is_hidden_but_its_stored_object_keeps_ownership(
    analysis_db, tmp_path
):
    job, _ = await completed(analysis_db, tmp_path)
    key = f"analyses/{job.id}/runs/1/reports/{job.current_report_id}/report.html"
    async with analysis_db.sessions() as session, session.begin():
        session.add(
            AnalysisReportArtifactRow(
                report_id=job.current_report_id,
                format="html",
                bucket="private-test",
                object_key=key,
                content_type="text/html",
                size_bytes=20,
                sha256="a" * 64,
                status="available",
            )
        )
    current = await analysis_db.repository.get_latest_report(job.id)
    assert {item.format for item in current.artifacts} == {"markdown", "docx"}
    reports = SqlAlchemyAnalysisReportRepository(analysis_db.sessions)
    assert key in await reports.expected_report_object_keys()
