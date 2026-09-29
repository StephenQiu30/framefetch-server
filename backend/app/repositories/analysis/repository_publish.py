"""Atomic strict-result persistence and successful analysis transition."""

from __future__ import annotations

import hashlib
from uuid import uuid4

from sqlalchemy import select

from app.core.db import as_utc
from app.models import AnalysisJobRow, AnalysisResultRow
from app.repositories.analysis.repository_base import AnalysisRepositoryBase
from app.repositories.analysis.repository_mapping import analysis_job_snapshot
from app.repositories.analysis.repository_serialization import analysis_result_document
from app.services.analysis.errors import PersistenceConflict, PersistenceNotFound
from app.services.analysis.models import AnalysisJobSnapshot, AnalysisPublish
from app.services.analysis.report import render_analysis_report_markdown
from app.services.analysis.rules.contracts import contract_for_result
from app.services.analysis.rules.enums import (
    AnalysisReportStatus,
    AnalysisStage,
    AnalysisStatus,
)
from app.services.identifiers import AnalysisReportRenderer


class AnalysisPublishRepository(AnalysisRepositoryBase):
    async def publish_result(self, command: AnalysisPublish) -> AnalysisJobSnapshot:
        document = analysis_result_document(command.result)
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(AnalysisJobRow)
                .where(AnalysisJobRow.id == command.job_id)
                .with_for_update()
            )
            if row is None:
                raise PersistenceNotFound("analysis job does not exist")
            if row.active_run_id != command.run_id:
                raise PersistenceConflict("analysis publish run is no longer active")
            run = await self.active_run(session, row, for_update=True)
            if (
                row.status == AnalysisStatus.SUCCEEDED.value
                or row.stage == AnalysisStage.PUBLISHING.value
            ):
                stored = await session.scalar(
                    select(AnalysisResultRow).where(
                        AnalysisResultRow.run_id == command.run_id
                    )
                )
                if stored is None or stored.result_json != document:
                    raise PersistenceConflict("analysis result replay differs")
                return analysis_job_snapshot(row)
            if (
                row.status != "running"
                or row.stage != "validating"
                or row.lease_owner != command.lease_owner
                or row.lease_expires_at is None
                or as_utc(row.lease_expires_at) <= as_utc(command.now)
                or row.version != command.expected_version
            ):
                raise PersistenceConflict("analysis publish lease or version lost")
            contract = contract_for_result(command.result)
            if (
                row.output_language != contract.language(command.result)
                or row.result_contract != contract.contract.value
            ):
                raise PersistenceConflict("analysis result contract differs from job")
            report_id = uuid4()
            markdown = render_analysis_report_markdown(command.result)
            markdown_sha256 = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
            session.add(
                AnalysisResultRow(
                    id=report_id,
                    job_id=row.id,
                    run_id=run.id,
                    input_sha256=row.input_sha256,
                    language=contract.language(command.result),
                    provider=command.provider,
                    model=command.model,
                    cli_version=command.cli_version,
                    result_json=document,
                    report_markdown=markdown,
                    content_sha256=markdown_sha256,
                    renderer_version=AnalysisReportRenderer.DEFAULT,
                    status=AnalysisReportStatus.VALIDATED.value,
                    attempt=0,
                    created_at=command.now,
                )
            )
            row.status = "running"
            row.stage = AnalysisStage.PUBLISHING.value
            row.stage_rank = 4
            row.progress = 95
            row.version += 1
            row.finished_at = None
            row.error_code = None
            row.error_message = None
            row.lease_owner = None
            row.lease_expires_at = None
            row.heartbeat_at = None
            row.updated_at = command.now
            run.provider = command.provider
            run.model = command.model
            run.cli_version = command.cli_version
            self.sync_run(row, run)
            run.status = "running"
            run.stage = AnalysisStage.PUBLISHING.value
            run.stage_rank = 4
            run.progress = 95
            report_event = self.report_requested_event(
                row, run, report_id, uuid4(), command.now
            )
            session.add(report_event)
            await session.flush()
            return analysis_job_snapshot(row)
