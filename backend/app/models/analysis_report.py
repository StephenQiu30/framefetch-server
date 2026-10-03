"""Immutable analysis report versions and their private object metadata."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import JSON_DOCUMENT, Base, utc_now
from app.services.analysis.rules.enums import (
    AnalysisReportArtifactStatus,
    AnalysisReportStatus,
)

_REPORT_STATUS_SQL_VALUES = ", ".join(
    f"'{status.value}'" for status in AnalysisReportStatus
)
_ARTIFACT_STATUS_SQL_VALUES = ", ".join(
    f"'{status.value}'" for status in AnalysisReportArtifactStatus
)


class AnalysisReportVersionRow(Base):
    __tablename__ = "analysis_report_versions"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_analysis_report_versions_run"),
        CheckConstraint(
            f"status IN ({_REPORT_STATUS_SQL_VALUES})",
            name="ck_analysis_report_versions_status",
        ),
        CheckConstraint(
            "length(input_sha256) = 64", name="ck_analysis_report_versions_input_sha"
        ),
        CheckConstraint(
            "length(content_sha256) = 64",
            name="ck_analysis_report_versions_content_sha",
        ),
        CheckConstraint("attempt >= 0", name="ck_analysis_report_versions_attempt"),
        CheckConstraint(
            "jsonb_typeof(result_json) = 'object'",
            name="ck_analysis_report_versions_json_object",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "result_json ? 'kind' AND result_json ->> 'kind' IN ("
            "'video_visual_analysis','video_article',"
            "'screenplay_analysis','screenplay_rewrite','structured_report','content_document')",
            name="ck_analysis_report_versions_result_kind",
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(35), nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    report_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    renderer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    cli_version: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=AnalysisReportStatus.VALIDATED.value
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalysisReportArtifactRow(Base):
    __tablename__ = "analysis_report_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "report_id", "format", name="uq_analysis_report_artifacts_format"
        ),
        UniqueConstraint(
            "bucket", "object_key", name="uq_analysis_report_artifacts_object"
        ),
        CheckConstraint(
            "format IN ('markdown','docx','html')",
            name="ck_analysis_report_artifacts_format",
        ),
        CheckConstraint(
            f"status IN ({_ARTIFACT_STATUS_SQL_VALUES})",
            name="ck_analysis_report_artifacts_status",
        ),
        CheckConstraint("size_bytes > 0", name="ck_analysis_report_artifacts_size"),
        CheckConstraint("length(sha256) = 64", name="ck_analysis_report_artifacts_sha"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    report_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("analysis_report_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=AnalysisReportArtifactStatus.AVAILABLE.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Transitional import name for callers; there is only one writable table.
AnalysisResultRow = AnalysisReportVersionRow
