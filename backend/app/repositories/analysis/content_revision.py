"""Atomic CAS revision, immutable report and existing publication Outbox."""

import hashlib
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from app.models import (
    AnalysisJobRow,
    AnalysisResultRow,
    AnalysisRetryOperationRow,
    AnalysisRunRow,
)
from app.repositories.analysis.repository_base import AnalysisRepositoryBase
from app.repositories.analysis.repository_mapping import analysis_job_snapshot
from app.repositories.analysis.run_factory import new_analysis_run
from app.repositories.quota_admission import lock_admission, reserve
from app.services.analysis.content_report import render_content_markdown
from app.services.analysis.content_versions import ContentVersion
from app.services.analysis.errors import (
    PersistenceConflict,
    PersistenceIdempotencyConflict,
    PersistenceNotFound,
)
from app.services.analysis.models import AnalysisJobSnapshot
from app.services.analysis.rules.content_document import (
    ContentDocumentResult,
    ContentDraft,
    ContentFinding,
    ContentReview,
    ContentSourceSet,
)
from app.services.identifiers import AnalysisReportRenderer
from app.services.quotas import DEFAULT_USER_QUOTA, UserQuota


class ContentRevisionRepository(AnalysisRepositoryBase):
    async def revise_content(
        self,
        job_id: UUID,
        owner_hash: str,
        base_report_id: UUID,
        draft: ContentDraft,
        idempotency_key: str,
        *,
        now: datetime,
        quota: UserQuota = DEFAULT_USER_QUOTA,
    ) -> AnalysisJobSnapshot:
        fingerprint = hashlib.sha256(
            (str(base_report_id) + draft.model_dump_json()).encode()
        ).hexdigest()
        async with self._sessions() as session, session.begin():
            await lock_admission(session, owner_hash)
            job = await session.scalar(
                select(AnalysisJobRow)
                .where(
                    AnalysisJobRow.id == job_id,
                    AnalysisJobRow.owner_hash == owner_hash,
                    AnalysisJobRow.deleted_at.is_(None),
                    AnalysisJobRow.input_kind == "content",
                )
                .with_for_update()
            )
            if job is None or job.content_source is None:
                raise PersistenceNotFound("content task is unavailable")
            replay = await session.scalar(
                select(AnalysisRetryOperationRow).where(
                    AnalysisRetryOperationRow.job_id == job.id,
                    AnalysisRetryOperationRow.operation == "edit",
                    AnalysisRetryOperationRow.idempotency_key == idempotency_key,
                )
            )
            if replay is not None:
                if replay.request_sha256 != fingerprint:
                    raise PersistenceIdempotencyConflict("revision request changed")
                return analysis_job_snapshot(job)
            if (
                job.status not in {"succeeded", "failed", "cancelled"}
                or job.current_report_id != base_report_id
                or job.current_run_no >= 50
            ):
                raise PersistenceConflict("revision base is no longer current")
            draft.validate_sources(ContentSourceSet.model_validate(job.content_source))
            if draft.language != job.output_language:
                raise ValueError("revision language differs from task")
            result = ContentDocumentResult(
                **draft.model_dump(),
                kind="content_document",
                source_set_ref=job.input_sha256,
                review_status="needs_review",
                review_history=(
                    ContentReview(
                        needs_material=False,
                        findings=(
                            ContentFinding(
                                block_id=draft.blocks[0].id,
                                severity="major",
                                category="expression",
                                problem="正文已人工修改，原审阅结论不再适用。",
                                correction="请核对修改后的事实、引语与表达。",
                            ),
                        ),
                    ),
                ),
            )
            run = new_analysis_run(
                run_id=uuid4(),
                job_id=job.id,
                run_no=job.current_run_no + 1,
                trigger="manual_edit",
                max_attempts=1,
                now=now,
            )
            await reserve(
                session,
                self._quota_policy,
                owner_hash=owner_hash,
                resource_id=run.id,
                kind="analysis",
                analysis_attempts=0,
                now=now,
                quota=quota,
            )
            session.add(run)
            await session.flush()
            report_id = uuid4()
            markdown = render_content_markdown(result)
            session.add(
                AnalysisResultRow(
                    id=report_id,
                    job_id=job.id,
                    run_id=run.id,
                    input_sha256=job.input_sha256,
                    language=draft.language,
                    result_json=result.model_dump(mode="json"),
                    report_markdown=markdown,
                    content_sha256=hashlib.sha256(markdown.encode()).hexdigest(),
                    renderer_version=AnalysisReportRenderer.DEFAULT,
                    provider="manual",
                    model="none",
                    cli_version="none",
                    status="validated",
                    attempt=0,
                    created_at=now,
                )
            )
            session.add(
                AnalysisRetryOperationRow(
                    job_id=job.id,
                    run_id=run.id,
                    operation="edit",
                    idempotency_key=idempotency_key,
                    request_sha256=fingerprint,
                    created_at=now,
                )
            )
            job.active_run_id = run.id
            job.current_run_no = run.run_no
            job.current_run_trigger = run.trigger
            job.status = "running"
            job.stage = "publishing"
            job.stage_rank = 4
            job.progress = 95
            job.attempt = 0
            job.max_attempts = 1
            job.version += 1
            job.lease_owner = None
            job.lease_expires_at = None
            job.heartbeat_at = None
            job.started_at = now
            job.finished_at = None
            job.retry_at = None
            job.cancel_requested_at = None
            job.error_code = None
            job.error_message = None
            job.updated_at = now
            self.sync_run(job, run)
            run.provider, run.model, run.cli_version = "manual", "none", "none"
            session.add(self.report_requested_event(job, run, report_id, uuid4(), now))
            await session.flush()
            return analysis_job_snapshot(job)

    async def content_versions(
        self, job_id: UUID, owner_hash: str
    ) -> tuple[ContentVersion, ...]:
        async with self._sessions() as session:
            job = await session.scalar(
                select(AnalysisJobRow.id).where(
                    AnalysisJobRow.id == job_id,
                    AnalysisJobRow.owner_hash == owner_hash,
                    AnalysisJobRow.deleted_at.is_(None),
                    AnalysisJobRow.input_kind == "content",
                )
            )
            if job is None:
                raise PersistenceNotFound("content task is unavailable")
            rows = (
                await session.execute(
                    select(AnalysisResultRow, AnalysisRunRow.run_no)
                    .join(AnalysisRunRow, AnalysisRunRow.id == AnalysisResultRow.run_id)
                    .where(
                        AnalysisResultRow.job_id == job_id,
                        AnalysisResultRow.status == "available",
                    )
                    .order_by(AnalysisRunRow.run_no.desc())
                    .limit(50)
                )
            ).all()
            return tuple(
                ContentVersion(
                    id=row.id,
                    run_no=run_no,
                    created_at=row.created_at,
                    result=ContentDocumentResult.model_validate(row.result_json),
                    markdown=row.report_markdown,
                    content_sha256=row.content_sha256,
                )
                for row, run_no in rows
            )
