"""Append-only analysis runs, retry operations and model step journal."""

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
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utc_now


class AnalysisRunRow(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        UniqueConstraint("job_id", "run_no", name="uq_analysis_runs_job_no"),
        CheckConstraint(
            "trigger IN ('initial','manual_retry','manual_rerun','manual_edit')",
            name="ck_analysis_runs_trigger",
        ),
        CheckConstraint(
            "status IN ("
            "'queued','running','retry_wait','succeeded','failed','cancelled'"
            ")",
            name="ck_analysis_runs_status",
        ),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_analysis_runs_progress"),
        CheckConstraint("attempt >= 0", name="ck_analysis_runs_attempt"),
        CheckConstraint("max_attempts > 0", name="ck_analysis_runs_max_attempts"),
        CheckConstraint("model_calls_used >= 0", name="ck_analysis_runs_model_calls"),
        CheckConstraint("version >= 0", name="ck_analysis_runs_version"),
        CheckConstraint(
            "stage_rank BETWEEN 0 AND 4", name="ck_analysis_runs_stage_rank"
        ),
        Index("ix_analysis_runs_job_created", "job_id", "created_at"),
        Index("ix_analysis_runs_claim", "status", "retry_at"),
        Index("ix_analysis_runs_stale", "status", "lease_expires_at"),
    )

    execution_binding: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True)
    )
    execution_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model_calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_no: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    stage: Mapped[str | None] = mapped_column(String(24))
    stage_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128))
    cli_version: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class AnalysisRetryOperationRow(Base):
    __tablename__ = "analysis_retry_operations"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "operation",
            "idempotency_key",
            name="uq_analysis_retry_operations_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    request_sha256: Mapped[str | None] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class AnalysisStepResultRow(Base):
    """One model call per run and step; a started row without payload is unknown."""

    __tablename__ = "analysis_step_results"
    __table_args__ = (
        CheckConstraint(
            "status IN ('started', 'succeeded', 'failed')",
            name="ck_analysis_step_results_status",
        ),
        CheckConstraint(
            "length(input_sha256) = 64", name="ck_analysis_step_results_input_sha"
        ),
        CheckConstraint(
            "(status IN ('succeeded', 'failed')) = (payload IS NOT NULL)",
            name="ck_analysis_step_results_payload",
        ),
    )

    run_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    step_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # none_as_null: a cleared payload must be SQL NULL for the status check.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
