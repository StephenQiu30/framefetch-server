"""Report retention, deletion, and orphan-protection persistence."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AnalysisJobRow,
    AnalysisReportArtifactRow,
    AnalysisResultRow,
    AnalysisRunRow,
)
from app.repositories.analysis.repository_base import AnalysisRepositoryBase
from app.services.analysis.rules.enums import (
    AnalysisReportArtifactStatus,
    AnalysisReportStatus,
    AnalysisResultKind,
    AnalysisStatus,
)


@dataclass(frozen=True, slots=True)
class ReportPurgeResult:
    deleted: int
    failed: int


class AnalysisReportLifecycleRepository(AnalysisRepositoryBase):
    async def purge_report_artifacts(
        self,
        now: datetime,
        delete: Callable[[str], Awaitable[None]],
        *,
        limit: int = 50,
    ) -> ReportPurgeResult:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        deleted = failed = 0
        excluded: list[UUID] = []
        for _ in range(limit):
            async with self._sessions() as session, session.begin():
                statement = (
                    select(AnalysisReportArtifactRow)
                    .where(
                        AnalysisReportArtifactRow.deleted_at.is_(None),
                        AnalysisReportArtifactRow.status
                        == AnalysisReportArtifactStatus.DELETE_PENDING.value,
                    )
                    .order_by(
                        AnalysisReportArtifactRow.created_at,
                        AnalysisReportArtifactRow.id,
                    )
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                if excluded:
                    statement = statement.where(
                        ~AnalysisReportArtifactRow.id.in_(excluded)
                    )
                artifact = await session.scalar(statement)
                if artifact is None:
                    break
                artifact.status = AnalysisReportArtifactStatus.DELETE_PENDING.value
                try:
                    await delete(artifact.object_key)
                except Exception:
                    failed += 1
                    excluded.append(artifact.id)
                    continue
                artifact.status = AnalysisReportArtifactStatus.DELETED.value
                artifact.deleted_at = now
                await self._finish_report_deletion(session, artifact.report_id)
                deleted += 1
        unpublished = await self._purge_unpublished(
            now, delete, limit=max(0, limit - deleted)
        )
        return ReportPurgeResult(
            deleted + unpublished.deleted, failed + unpublished.failed
        )

    async def _purge_unpublished(
        self, now: datetime, delete: Callable[[str], Awaitable[None]], *, limit: int
    ) -> ReportPurgeResult:
        deleted = failed = 0
        async with self._sessions() as session, session.begin():
            inactive = or_(
                AnalysisJobRow.status.not_in(
                    (
                        AnalysisStatus.QUEUED.value,
                        AnalysisStatus.RUNNING.value,
                        AnalysisStatus.RETRY_WAIT.value,
                    )
                ),
                AnalysisJobRow.active_run_id != AnalysisResultRow.run_id,
            )
            has_artifacts = exists().where(
                AnalysisReportArtifactRow.report_id == AnalysisResultRow.id
            )
            rows = (
                await session.execute(
                    select(AnalysisResultRow, AnalysisRunRow.run_no)
                    .join(AnalysisRunRow, AnalysisRunRow.id == AnalysisResultRow.run_id)
                    .join(AnalysisJobRow, AnalysisJobRow.id == AnalysisResultRow.job_id)
                    .where(
                        ~has_artifacts,
                        or_(
                            AnalysisResultRow.status
                            == AnalysisReportStatus.DELETE_PENDING.value,
                            (
                                AnalysisResultRow.status
                                == AnalysisReportStatus.PUBLISHING.value
                            )
                            & inactive
                            & (AnalysisResultRow.lease_expires_at <= now),
                        ),
                    )
                    .order_by(AnalysisResultRow.created_at)
                    .limit(limit)
                    .with_for_update(of=AnalysisResultRow, skip_locked=True)
                )
            ).all()
            for report, run_no in rows:
                report.status = AnalysisReportStatus.DELETE_PENDING.value
                try:
                    prefix = (
                        f"analyses/{report.job_id}/runs/{run_no}/reports/{report.id}"
                    )
                    await delete(f"{prefix}/report.md")
                    await delete(f"{prefix}/report.docx")
                    if (
                        report.result_json.get("kind")
                        == AnalysisResultKind.CONTENT_DOCUMENT.value
                    ):
                        # Clean up a previously uploaded retired format as well.
                        await delete(f"{prefix}/report.html")
                except Exception:
                    failed += 1
                    continue
                report.status = AnalysisReportStatus.DELETED.value
                report.lease_owner = None
                report.lease_expires_at = None
                deleted += 1
        return ReportPurgeResult(deleted, failed)

    async def expected_report_object_keys(self) -> frozenset[str]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(
                        AnalysisResultRow.id,
                        AnalysisResultRow.job_id,
                        AnalysisRunRow.run_no,
                    )
                    .join(AnalysisRunRow, AnalysisRunRow.id == AnalysisResultRow.run_id)
                    .where(
                        AnalysisResultRow.status != AnalysisReportStatus.DELETED.value
                    )
                )
            ).all()
            # Stored objects from retired formats remain owned until task deletion.
            recorded = (
                await session.scalars(
                    select(AnalysisReportArtifactRow.object_key).where(
                        AnalysisReportArtifactRow.deleted_at.is_(None)
                    )
                )
            ).all()
        return frozenset(recorded) | frozenset(
            f"analyses/{job_id}/runs/{run_no}/reports/{report_id}/report.{suffix}"
            for report_id, job_id, run_no in rows
            for suffix in ("md", "docx")
        )

    @staticmethod
    async def _finish_report_deletion(session: AsyncSession, report_id: UUID) -> None:
        remaining = await session.scalar(
            select(func.count())
            .select_from(AnalysisReportArtifactRow)
            .where(
                AnalysisReportArtifactRow.report_id == report_id,
                AnalysisReportArtifactRow.deleted_at.is_(None),
            )
        )
        if remaining:
            return
        report = await session.get(AnalysisResultRow, report_id)
        if report is not None:
            report.status = AnalysisReportStatus.DELETED.value
