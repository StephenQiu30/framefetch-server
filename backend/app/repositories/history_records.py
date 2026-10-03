"""Unified history and deadline expiry of parse intents and analysis jobs."""

from typing import Any
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import (
    DateTime,
    Integer,
    LargeBinary,
    String,
    Uuid,
    and_,
    case,
    cast,
    exists,
    func,
    literal,
    null,
    or_,
    select,
    union_all,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.selectable import Select, Subquery

from app.core.db import JSON_DOCUMENT, utc_now
from app.models.analysis import AnalysisJobRow
from app.models.analysis_report import AnalysisReportVersionRow
from app.models.analysis_run import AnalysisRunRow
from app.models.document import DocumentArtifactRow, DocumentRow
from app.models.download import ArtifactRow, DownloadJobRow
from app.models.download_intent import DownloadIntentRow
from app.models.media import MediaInspectionRow
from app.models.media_import import MediaImportRow
from app.repositories.downloads.intent_repository import request_overdue_cleanup
from app.services.downloads.inspection_models import EncryptedUrl
from app.services.history_records import (
    DEFAULT_HISTORY_FILTERS,
    AnalysisRunHistory,
    HistoryAvailability,
    HistoryRecordCursor,
    HistoryRecordFilters,
    HistoryRecordKind,
    HistoryRecordPage,
    HistoryRecordSnapshot,
)
from app.services.provider_failures import ProviderFailure

PROVIDER_FAILURE = TypeAdapter(ProviderFailure)


class SqlAlchemyHistoryRecordRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def history(
        self,
        owner_hash: str,
        *,
        before: HistoryRecordCursor | None,
        limit: int,
        filters: HistoryRecordFilters = DEFAULT_HISTORY_FILTERS,
    ) -> HistoryRecordPage:
        intent_records = (
            select(
                literal(HistoryRecordKind.PARSE.value).label("record_type"),
                DownloadIntentRow.id.label("id"),
                MediaInspectionRow.title.label("title"),
                DownloadIntentRow.created_at.label("created_at"),
                DownloadIntentRow.status.label("status"),
                DownloadIntentRow.version.label("version"),
                DownloadIntentRow.reason_code.label("reason_code"),
                DownloadIntentRow.latest_failure.label("latest_failure"),
                cast(null(), DateTime(timezone=True)).label("retry_at"),
                DownloadIntentRow.deadline.label("deadline"),
                DownloadIntentRow.inspection_id.label("inspection_id"),
                DownloadIntentRow.job_id.label("job_id"),
                cast(null(), Uuid).label("download_id"),
                cast(null(), String).label("skill_id"),
                cast(null(), Integer).label("progress"),
                cast(null(), String).label("stage"),
                cast(null(), String).label("error_code"),
                DownloadIntentRow.url_ciphertext.label("url_ciphertext"),
                DownloadIntentRow.url_nonce.label("url_nonce"),
                DownloadIntentRow.url_key_id.label("url_key_id"),
                DownloadIntentRow.request_fingerprint.label("request_fingerprint"),
                DownloadIntentRow.updated_at.label("updated_at"),
                cast(null(), Uuid).label("document_id"),
                cast(null(), Uuid).label("artifact_id"),
                cast(null(), String).label("source_format"),
                cast(null(), String).label("output_language"),
                cast(null(), String).label("result_contract"),
                cast(null(), Integer).label("current_run_no"),
                cast(null(), DateTime(timezone=True)).label("cancel_requested_at"),
                literal("not_applicable").label("source_availability"),
                case(
                    (MediaInspectionRow.expires_at > utc_now(), "available"),
                    else_="unavailable",
                ).label("result_availability"),
            )
            .outerjoin(
                MediaInspectionRow,
                and_(
                    MediaInspectionRow.id == DownloadIntentRow.inspection_id,
                    MediaInspectionRow.owner_hash == owner_hash,
                ),
            )
            .where(DownloadIntentRow.owner_hash == owner_hash)
        )
        analysis_records = (
            select(
                case(
                    (AnalysisJobRow.input_kind == "video", "video_analysis"),
                    (AnalysisJobRow.input_kind == "content", "content_creation"),
                    else_="screenplay_analysis",
                ).label("record_type"),
                AnalysisJobRow.id.label("id"),
                func.coalesce(
                    AnalysisReportVersionRow.result_json["title"].as_string(),
                    DocumentRow.title,
                    MediaInspectionRow.title,
                    MediaImportRow.display_name,
                    case(
                        (AnalysisJobRow.input_kind == "video", "视频"),
                        (AnalysisJobRow.input_kind == "content", "内容创作"),
                        else_="剧本",
                    ),
                ).label("title"),
                AnalysisJobRow.created_at.label("created_at"),
                AnalysisJobRow.status.label("status"),
                AnalysisJobRow.version.label("version"),
                cast(null(), String).label("reason_code"),
                cast(null(), JSON_DOCUMENT).label("latest_failure"),
                cast(null(), DateTime(timezone=True)).label("retry_at"),
                cast(null(), DateTime(timezone=True)).label("deadline"),
                cast(null(), Uuid).label("inspection_id"),
                cast(null(), Uuid).label("job_id"),
                DownloadJobRow.id.label("download_id"),
                AnalysisJobRow.skill_id.label("skill_id"),
                AnalysisJobRow.progress.label("progress"),
                AnalysisJobRow.stage.label("stage"),
                AnalysisJobRow.error_code.label("error_code"),
                cast(null(), LargeBinary).label("url_ciphertext"),
                cast(null(), LargeBinary).label("url_nonce"),
                cast(null(), String).label("url_key_id"),
                cast(null(), String).label("request_fingerprint"),
                AnalysisJobRow.updated_at.label("updated_at"),
                DocumentRow.id.label("document_id"),
                ArtifactRow.id.label("artifact_id"),
                cast(null(), String).label("source_format"),
                AnalysisJobRow.output_language.label("output_language"),
                AnalysisJobRow.result_contract.label("result_contract"),
                AnalysisJobRow.current_run_no.label("current_run_no"),
                AnalysisJobRow.cancel_requested_at.label("cancel_requested_at"),
                case(
                    (
                        and_(
                            AnalysisJobRow.input_kind == "content",
                            AnalysisJobRow.content_source.is_not(None),
                        ),
                        "available",
                    ),
                    (
                        and_(
                            AnalysisJobRow.input_kind == "screenplay",
                            DocumentRow.deleted_at.is_(None),
                            DocumentRow.status == "ready",
                            DocumentArtifactRow.status == "ready",
                        ),
                        "available",
                    ),
                    (
                        and_(
                            AnalysisJobRow.input_kind == "video",
                            DownloadJobRow.status == "succeeded",
                            ArtifactRow.id.is_not(None),
                            ArtifactRow.deleted_at.is_(None),
                        ),
                        "available",
                    ),
                    else_="unavailable",
                ).label("source_availability"),
                case(
                    (AnalysisReportVersionRow.status == "available", "available"),
                    else_="unavailable",
                ).label("result_availability"),
            )
            .select_from(AnalysisJobRow)
            .outerjoin(
                ArtifactRow,
                and_(
                    ArtifactRow.id == AnalysisJobRow.artifact_id,
                    exists(
                        select(DownloadJobRow.id)
                        .where(
                            DownloadJobRow.id == ArtifactRow.job_id,
                            DownloadJobRow.owner_hash == owner_hash,
                        )
                        .correlate(ArtifactRow)
                    ),
                ),
            )
            .outerjoin(
                DocumentRow,
                and_(
                    DocumentRow.id == AnalysisJobRow.document_id,
                    DocumentRow.owner_hash == owner_hash,
                ),
            )
            .outerjoin(
                DocumentArtifactRow,
                and_(
                    DocumentArtifactRow.document_id == DocumentRow.id,
                    DocumentArtifactRow.kind == "normalized",
                ),
            )
            .outerjoin(
                AnalysisReportVersionRow,
                and_(
                    AnalysisReportVersionRow.id == AnalysisJobRow.current_report_id,
                    AnalysisReportVersionRow.job_id == AnalysisJobRow.id,
                ),
            )
            .outerjoin(
                DownloadJobRow,
                and_(
                    DownloadJobRow.id == ArtifactRow.job_id,
                    DownloadJobRow.owner_hash == owner_hash,
                ),
            )
            .outerjoin(
                MediaInspectionRow,
                and_(
                    MediaInspectionRow.id == DownloadJobRow.inspection_id,
                    MediaInspectionRow.owner_hash == owner_hash,
                ),
            )
            .outerjoin(
                MediaImportRow,
                and_(
                    MediaImportRow.id == DownloadJobRow.id,
                    MediaImportRow.owner_hash == owner_hash,
                ),
            )
            .where(
                AnalysisJobRow.owner_hash == owner_hash,
                AnalysisJobRow.deleted_at.is_(None),
            )
        )
        document_records = (
            select(
                literal("document_parse").label("record_type"),
                DocumentRow.id.label("id"),
                DocumentRow.title.label("title"),
                DocumentRow.created_at.label("created_at"),
                DocumentRow.status.label("status"),
                DocumentRow.version.label("version"),
                cast(null(), String).label("reason_code"),
                cast(null(), JSON_DOCUMENT).label("latest_failure"),
                cast(null(), DateTime(timezone=True)).label("retry_at"),
                cast(null(), DateTime(timezone=True)).label("deadline"),
                cast(null(), Uuid).label("inspection_id"),
                cast(null(), Uuid).label("job_id"),
                cast(null(), Uuid).label("download_id"),
                cast(null(), String).label("skill_id"),
                cast(null(), Integer).label("progress"),
                cast(null(), String).label("stage"),
                DocumentRow.error_code.label("error_code"),
                cast(null(), LargeBinary).label("url_ciphertext"),
                cast(null(), LargeBinary).label("url_nonce"),
                cast(null(), String).label("url_key_id"),
                cast(null(), String).label("request_fingerprint"),
                DocumentRow.updated_at.label("updated_at"),
                DocumentRow.id.label("document_id"),
                cast(null(), Uuid).label("artifact_id"),
                DocumentRow.source_format.label("source_format"),
                cast(null(), String).label("output_language"),
                cast(null(), String).label("result_contract"),
                cast(null(), Integer).label("current_run_no"),
                cast(null(), DateTime(timezone=True)).label("cancel_requested_at"),
                literal("not_applicable").label("source_availability"),
                case(
                    (DocumentArtifactRow.status == "ready", "available"),
                    else_="unavailable",
                ).label("result_availability"),
            )
            .outerjoin(
                DocumentArtifactRow,
                and_(
                    DocumentArtifactRow.document_id == DocumentRow.id,
                    DocumentArtifactRow.kind == "normalized",
                ),
            )
            .where(
                DocumentRow.owner_hash == owner_hash, DocumentRow.deleted_at.is_(None)
            )
        )
        # Each branch applies the same filter and cursor BEFORE its top-K limit.
        # This bounds the global merge without dropping any eligible record.
        candidates = [
            _page_statement(
                branch.subquery(), before=before, limit=limit + 1, filters=filters
            ).subquery()
            for branch in (intent_records, analysis_records, document_records)
        ]
        records = union_all(*(select(candidate) for candidate in candidates)).subquery(
            "history_records"
        )
        statement = (
            select(records)
            .order_by(
                records.c.created_at.desc(),
                records.c.id.desc(),
                records.c.record_type.desc(),
            )
            .limit(limit + 1)
        )

        async with self._sessions() as session, session.begin():
            now = utc_now()
            await request_overdue_cleanup(session, owner_hash, now)
            rows = (await session.execute(statement)).mappings().all()

        has_more = len(rows) > limit
        items = tuple(
            HistoryRecordSnapshot(
                id=row["id"],
                record_type=HistoryRecordKind(row["record_type"]),
                title=row["title"],
                created_at=row["created_at"],
                status=row["status"],
                updated_at=row["updated_at"],
                document_id=row["document_id"],
                artifact_id=row["artifact_id"],
                source_format=row["source_format"],
                output_language=row["output_language"],
                result_contract=row["result_contract"],
                current_run_no=row["current_run_no"],
                cancel_requested_at=row["cancel_requested_at"],
                source_availability=HistoryAvailability(row["source_availability"]),
                result_availability=HistoryAvailability(row["result_availability"]),
                version=row["version"],
                reason_code=row["reason_code"],
                latest_failure=None
                if row["latest_failure"] is None
                else PROVIDER_FAILURE.validate_python(row["latest_failure"]),
                retry_at=row["retry_at"],
                deadline=row["deadline"],
                inspection_id=row["inspection_id"],
                job_id=row["job_id"],
                download_id=row["download_id"],
                skill_id=row["skill_id"],
                progress=row["progress"],
                stage=row["stage"],
                error_code=row["error_code"],
                encrypted_url=(
                    EncryptedUrl(
                        row["url_ciphertext"], row["url_nonce"], row["url_key_id"]
                    )
                    if row["url_ciphertext"] is not None
                    else None
                ),
                request_fingerprint=row["request_fingerprint"],
            )
            for row in rows[:limit]
        )
        last = items[-1] if has_more and items else None
        cursor = (
            None
            if last is None
            else HistoryRecordCursor(last.created_at, last.record_type, last.id)
        )
        return HistoryRecordPage(items, cursor)

    async def runs(
        self,
        owner_hash: str,
        analysis_id: UUID,
        *,
        before_run_no: int | None,
        limit: int,
    ) -> tuple[AnalysisRunHistory, ...]:
        statement = (
            select(AnalysisRunRow)
            .join(AnalysisJobRow, AnalysisJobRow.id == AnalysisRunRow.job_id)
            .where(
                AnalysisJobRow.owner_hash == owner_hash,
                AnalysisJobRow.deleted_at.is_(None),
                AnalysisJobRow.id == analysis_id,
            )
        )
        if before_run_no is not None:
            statement = statement.where(AnalysisRunRow.run_no < before_run_no)
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    statement.order_by(AnalysisRunRow.run_no.desc()).limit(limit)
                )
            ).all()
            return tuple(
                AnalysisRunHistory(
                    row.id,
                    row.run_no,
                    row.trigger,
                    row.status,
                    row.created_at,
                    row.started_at,
                    row.finished_at,
                    row.error_code,
                )
                for row in rows
            )

    async def inspection_titles(
        self,
        owner_hash: str,
        fingerprints: frozenset[str],
        youtube_ids: frozenset[str],
    ) -> dict[str, str]:
        if not fingerprints and not youtube_ids:
            return {}
        statement = (
            select(
                MediaInspectionRow.request_fingerprint,
                MediaInspectionRow.provider_media_id,
                MediaInspectionRow.extractor_key,
                MediaInspectionRow.title,
            )
            .where(
                MediaInspectionRow.owner_hash == owner_hash,
                or_(
                    MediaInspectionRow.request_fingerprint.in_(fingerprints),
                    and_(
                        func.lower(MediaInspectionRow.extractor_key) == "youtube",
                        MediaInspectionRow.provider_media_id.in_(youtube_ids),
                    ),
                ),
            )
            .order_by(MediaInspectionRow.created_at.desc())
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).all()
        titles: dict[str, str] = {}
        for fingerprint, media_id, extractor_key, title in rows:
            titles.setdefault(fingerprint, title)
            if extractor_key.lower() == "youtube":
                titles.setdefault(media_id, title)
        return titles


def _page_statement(
    records: Subquery,
    *,
    before: HistoryRecordCursor | None,
    limit: int,
    filters: HistoryRecordFilters,
) -> Select[Any]:
    statement = select(records)
    if filters.record_types:
        statement = statement.where(
            records.c.record_type.in_([kind.value for kind in filters.record_types])
        )
    if filters.status_group:
        group = case(
            (
                records.c.status.in_(["ready", "handed_off", "succeeded"]),
                "completed",
            ),
            (
                records.c.status.in_(["failed", "cancelled", "expired"]),
                records.c.status,
            ),
            else_="processing",
        )
        statement = statement.where(group == filters.status_group.value)
    if filters.created_from:
        statement = statement.where(records.c.created_at >= filters.created_from)
    if filters.created_to:
        statement = statement.where(records.c.created_at < filters.created_to)
    if filters.q:
        statement = statement.where(
            records.c.title.icontains(filters.q, autoescape=True)
        )
    for column, value in (
        (records.c.skill_id, filters.skill_id),
        (records.c.result_contract, filters.result_contract),
        (records.c.document_id, filters.document_id),
        (records.c.download_id, filters.download_id),
    ):
        if value is not None:
            statement = statement.where(column == value)
    if filters.analysis_id:
        statement = statement.where(
            records.c.id == filters.analysis_id,
            records.c.record_type.in_(
                ["video_analysis", "screenplay_analysis", "content_creation"]
            ),
        )
    if before is not None:
        statement = statement.where(
            or_(
                records.c.created_at < before.created_at,
                and_(
                    records.c.created_at == before.created_at,
                    records.c.id < before.id,
                ),
                and_(
                    records.c.created_at == before.created_at,
                    records.c.id == before.id,
                    records.c.record_type < before.record_type.value,
                ),
            )
        )
    statement = statement.order_by(
        records.c.created_at.desc(),
        records.c.id.desc(),
        records.c.record_type.desc(),
    ).limit(limit)

    return statement
