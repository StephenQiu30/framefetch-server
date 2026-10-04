from uuid import uuid4

import pytest
from app.integrations.analysis_report_docx import PythonDocxAnalysisReportRenderer
from app.integrations.object_storage import StoredObjectStat
from app.models import AnalysisReportArtifactRow, AnalysisResultRow, AnalysisRunRow
from app.repositories.analysis.execution import AnalysisExecutionPersistence
from app.repositories.analysis.report_repository import (
    SqlAlchemyAnalysisReportRepository,
)
from app.repositories.downloads.repository import SqlAlchemyDownloadRepository
from app.services.analysis.errors import (
    PersistenceConflict,
    PersistenceIdempotencyConflict,
    PersistenceNotFound,
)
from app.services.analysis.rules.content_document import ContentDraft
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
    resolver = Resolver(Analyzer([draft(), review()]))
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


async def test_content_publication_and_revision_preserve_original(
    analysis_db, tmp_path
):
    db = analysis_db
    job, storage = await completed(db, tmp_path)
    original_files = dict(storage.values)
    assert len(original_files) == 2
    assert {key.rsplit(".", 1)[-1] for key in original_files} == {"md", "docx"}
    original = await db.repository.get_result(job.id)
    edited = draft()
    edited["blocks"][1]["text"] = "这次观察只覆盖短暂倒置。"
    content = ContentDraft.model_validate(edited)
    key = str(uuid4())
    next_job = await db.repository.revise_content(
        job.id, OWNER, job.current_report_id, content, key, now=NOW
    )
    assert next_job.run_trigger == "manual_edit"
    assert next_job.current_report_id == job.current_report_id
    replay = await db.repository.revise_content(
        job.id, OWNER, job.current_report_id, content, key, now=NOW
    )
    assert replay.run_id == next_job.run_id
    with pytest.raises(PersistenceIdempotencyConflict):
        await db.repository.revise_content(
            job.id,
            OWNER,
            job.current_report_id,
            ContentDraft.model_validate(draft()),
            key,
            now=NOW,
        )
    with pytest.raises(PersistenceNotFound):
        await db.repository.revise_content(
            job.id, "b" * 64, job.current_report_id, content, str(uuid4()), now=NOW
        )
    final = await publish(db, storage, next_job)
    assert final.current_report_id != job.current_report_id
    assert all(storage.values[key] == value for key, value in original_files.items())
    assert len(storage.values) == 4
    result = await db.repository.get_result(job.id)
    assert result.review_status == "needs_review" and original.review_status == "passed"
    async with db.sessions() as session:
        run = await session.get(AnalysisRunRow, next_job.run_id)
        assert run.model_calls_used == 0
    versions = await db.repository.content_versions(job.id, OWNER)
    assert [item.run_no for item in versions] == [2, 1]
    assert versions[1].result == original
    assert versions[1].content_sha256 != versions[0].content_sha256
    with pytest.raises(PersistenceNotFound):
        await db.repository.content_versions(job.id, "b" * 64)
    with pytest.raises(PersistenceConflict):
        await db.repository.revise_content(
            job.id, OWNER, job.current_report_id, content, str(uuid4()), now=NOW
        )


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
