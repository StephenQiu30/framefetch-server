"""Atomic strict-result persistence and successful analysis transition."""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from sqlalchemy import select

from app.core.db import as_utc
from app.models import AnalysisJobRow, AnalysisReportArtifactRow, AnalysisResultRow
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
from app.services.analysis.rules.structured_report import StructuredReportResult
from app.services.identifiers import AnalysisReportRenderer


class AnalysisPublishRepository(AnalysisRepositoryBase):
    async def publish_result(self, command: AnalysisPublish) -> AnalysisJobSnapshot:
        document = analysis_result_document(command.result)
        if len(json.dumps(document, ensure_ascii=False).encode()) > 1024**2:
            raise PersistenceConflict("analysis result exceeds JSON byte limit")
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
            if isinstance(command.result, StructuredReportResult):
                if row.input_kind == "video" and command.result.media is None:
                    raise PersistenceConflict(
                        "video report requires authoritative media"
                    )
                if row.input_kind == "screenplay":
                    command.result.validate_document_source(row.input_sha256)
            report_id = uuid4()
            markdown = command.native_markdown or render_analysis_report_markdown(
                command.result
            )
            if command.native_markdown is not None and row.skill_id != "video-shots":
                raise PersistenceConflict("native Markdown does not match Skill")
            if len(markdown.encode()) > 1024**2:
                raise PersistenceConflict("native Markdown exceeds byte limit")
            binding = run.execution_binding
            if row.result_contract == "screenplay-analysis" and isinstance(
                binding, dict
            ):
                units = binding.get("source_units")
                if isinstance(units, list) and units:
                    lines = [
                        "",
                        "## 来源索引"
                        if row.output_language == "zh-CN"
                        else "## Source index",
                        "",
                        f"UTF-8 SHA256 `{row.input_sha256}` · Unicode",
                    ]
                    for index, unit in enumerate(units, start=1):
                        if (
                            not isinstance(unit, dict)
                            or type(unit.get("start")) is not int
                            or type(unit.get("end")) is not int
                        ):
                            raise PersistenceConflict("source index is invalid")
                        lines.append(f"- {index}: [{unit['start']}, {unit['end']})")
                    markdown += "\n".join(lines) + "\n"
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
            # There is no ORM relationship between these mappers. Flush the
            # parent inside this transaction before inserting native children.
            if command.native_artifacts:
                await session.flush()
            for artifact in command.native_artifacts:
                if (
                    row.skill_id != "video-shots"
                    or artifact.format != "zip"
                    or not command.native_bucket
                    or not artifact.object_key.startswith(
                        f"analyses/{row.id}/runs/{run.id}/native/"
                    )
                    or not 0 < artifact.size_bytes <= 16 * 1024**2
                ):
                    raise PersistenceConflict("native artifact is outside this run")
                session.add(
                    AnalysisReportArtifactRow(
                        id=uuid4(),
                        report_id=report_id,
                        format=artifact.format,
                        bucket=command.native_bucket,
                        object_key=artifact.object_key,
                        content_type=artifact.media_type,
                        size_bytes=artifact.size_bytes,
                        sha256=artifact.sha256,
                        status="available",
                        created_at=command.now,
                        available_at=command.now,
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
