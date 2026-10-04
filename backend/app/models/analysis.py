"""Persistence rows for independent AI analysis jobs and strict results."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utc_now


class AnalysisJobRow(Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (
        UniqueConstraint(
            "owner_hash",
            "idempotency_key",
            name="uq_analysis_jobs_owner_idempotency",
        ),
        CheckConstraint(
            "status IN ("
            "'queued','running','retry_wait','succeeded','failed','cancelled'"
            ")",
            name="ck_analysis_jobs_status",
        ),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_analysis_jobs_progress"),
        CheckConstraint("attempt >= 0", name="ck_analysis_jobs_attempt"),
        CheckConstraint("max_attempts > 0", name="ck_analysis_jobs_max_attempts"),
        CheckConstraint("version >= 0", name="ck_analysis_jobs_version"),
        CheckConstraint("current_run_no > 0", name="ck_analysis_jobs_run_no"),
        CheckConstraint(
            "status <> 'succeeded' OR current_report_id IS NOT NULL",
            name="ck_analysis_jobs_succeeded_report",
        ),
        CheckConstraint(
            "stage_rank BETWEEN 0 AND 4", name="ck_analysis_jobs_stage_rank"
        ),
        CheckConstraint(
            "length(input_sha256) = 64", name="ck_analysis_jobs_sha256_length"
        ),
        CheckConstraint(
            "length(skill_instructions_sha256) = 64",
            name="ck_analysis_jobs_skill_instructions_sha256",
        ),
        CheckConstraint(
            "input_kind IN ('video','screenplay','content','skill')",
            name="ck_analysis_jobs_input_kind",
        ),
        CheckConstraint(
            "result_contract IN ("
            "'video-visual-analysis','video-article','screenplay-analysis',"
            "'screenplay-rewrite','structured-report','content-document','skill-report'"
            ")",
            name="ck_analysis_jobs_result_contract",
        ),
        CheckConstraint(
            "(input_kind = 'skill' AND skill_inputs IS NOT NULL "
            "AND content_source IS NULL AND result_contract = 'skill-report') OR "
            "(input_kind = 'content' AND content_source IS NOT NULL "
            "AND artifact_id IS NULL AND document_id IS NULL "
            "AND result_contract = 'content-document') OR "
            "(input_kind = 'video' AND content_source IS NULL "
            "AND artifact_id IS NOT NULL "
            "AND document_id IS NULL AND result_contract IN ("
            "'video-visual-analysis','video-article','structured-report')) "
            "OR (input_kind = 'screenplay' AND content_source IS NULL "
            "AND artifact_id IS NULL "
            "AND document_id IS NOT NULL AND result_contract IN ("
            "'screenplay-analysis','screenplay-rewrite','structured-report'))",
            name="ck_analysis_jobs_input_shape",
        ),
        Index("ix_analysis_jobs_owner_created", "owner_hash", "created_at"),
        Index("ix_analysis_jobs_claim", "status", "retry_at"),
        Index("ix_analysis_jobs_stale", "status", "lease_expires_at"),
        Index("ix_analysis_jobs_queued_recovery", "status", "updated_at"),
        Index("ix_analysis_jobs_artifact", "artifact_id"),
        Index("ix_analysis_jobs_document", "document_id"),
    )

    skill_inputs: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True)
    )
    content_source: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True)
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    input_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="video")
    result_contract: Mapped[str] = mapped_column(
        String(32), nullable=False, default="video-visual-analysis"
    )
    artifact_id: Mapped[UUID | None] = mapped_column(Uuid)
    document_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "documents.id", ondelete="RESTRICT", name="fk_analysis_jobs_document"
        ),
    )
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    skill_id: Mapped[str] = mapped_column(String(128), nullable=False)
    skill_instructions: Mapped[str] = mapped_column(Text, nullable=False)
    skill_instructions_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output_language: Mapped[str] = mapped_column(String(35), nullable=False)
    custom_prompt: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    stage: Mapped[str | None] = mapped_column(String(24))
    stage_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_run_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    current_report_id: Mapped[UUID | None] = mapped_column(Uuid)
    current_run_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    current_run_trigger: Mapped[str] = mapped_column(
        String(24), nullable=False, default="initial"
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(512))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class AnalysisArtifactLockRow(Base):
    __tablename__ = "analysis_artifact_locks"
    __table_args__ = (Index("ix_analysis_artifact_locks_artifact", "artifact_id"),)

    job_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    artifact_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("artifacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
