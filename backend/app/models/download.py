"""Persistence rows for leased download jobs and verified artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import JSON_DOCUMENT, Base, utc_now
from app.models.execution_context import execution_context_check


class DownloadJobRow(Base):
    __tablename__ = "download_jobs"
    __table_args__ = (
        UniqueConstraint(
            "owner_hash",
            "idempotency_key",
            name="uq_download_jobs_owner_idempotency",
        ),
        CheckConstraint(
            "status IN ("
            "'queued','running','retry_wait','succeeded','failed','cancelled'"
            ")",
            name="ck_download_jobs_status",
        ),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_download_jobs_progress"),
        CheckConstraint("attempt >= 0", name="ck_download_jobs_attempt"),
        CheckConstraint(
            execution_context_check("execution_context"),
            name="ck_download_jobs_execution_context",
        ),
        CheckConstraint("max_attempts > 0", name="ck_download_jobs_max_attempts"),
        CheckConstraint("version >= 0", name="ck_download_jobs_version"),
        CheckConstraint(
            "stage_rank BETWEEN 0 AND 5", name="ck_download_jobs_stage_rank"
        ),
        CheckConstraint(
            "(source_kind = 'remote_provider' AND inspection_id IS NOT NULL "
            "AND format_id IS NOT NULL) OR "
            "(source_kind = 'browser_import' AND inspection_id IS NULL "
            "AND format_id IS NULL)",
            name="ck_download_jobs_source_shape",
        ),
        Index("ix_download_jobs_owner_created", "owner_hash", "created_at"),
        Index("ix_download_jobs_created", "created_at"),
        Index("ix_download_jobs_claim", "status", "retry_at"),
        Index("ix_download_jobs_stale", "status", "lease_expires_at"),
        Index("ix_download_jobs_queued_recovery", "status", "updated_at"),
        Index(
            "uq_download_jobs_owner_active_request",
            "owner_hash",
            "request_fingerprint",
            unique=True,
            postgresql_where=text(
                "source_kind = 'remote_provider' AND "
                "status IN ('queued','running','retry_wait')"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="remote_provider"
    )
    inspection_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("media_inspections.id")
    )
    format_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("media_formats.id"))
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    semantic_plan: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    execution_context: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True)
    )
    execution_context_attempt: Mapped[int | None] = mapped_column(Integer)
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class ArtifactRow(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_artifacts_job"),
        UniqueConstraint("bucket", "object_key", name="uq_artifacts_object"),
        CheckConstraint("attempt > 0", name="ck_artifacts_attempt"),
        CheckConstraint(
            execution_context_check("(media_metadata->'execution_context')"),
            name="ck_artifacts_execution_context",
        ),
        CheckConstraint("size_bytes > 0", name="ck_artifacts_size"),
        CheckConstraint("duration_ms > 0", name="ck_artifacts_duration"),
        CheckConstraint("length(sha256) = 64", name="ck_artifacts_sha256_length"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("download_jobs.id", ondelete="CASCADE"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    container: Mapped[str] = mapped_column(String(16), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    media_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
