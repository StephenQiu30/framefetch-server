"""Owner-scoped read-only history of published content reports."""

from uuid import UUID

from sqlalchemy import select

from app.models import AnalysisJobRow, AnalysisResultRow, AnalysisRunRow
from app.repositories.analysis.repository_base import AnalysisRepositoryBase
from app.services.analysis.content_versions import ContentVersion
from app.services.analysis.errors import PersistenceNotFound
from app.services.analysis.rules.content_document import ContentDocumentResult


class ContentVersionsRepository(AnalysisRepositoryBase):
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
                        # File cleanup must not hide previously published prose.
                        AnalysisResultRow.published_at.is_not(None),
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
