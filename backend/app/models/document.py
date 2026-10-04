"""Persistence rows for immutable screenplay documents and their artifacts."""

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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import JSON_DOCUMENT, Base, utc_now


class DocumentRow(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint(
            "owner_hash", "idempotency_key", name="uq_documents_owner_idempotency"
        ),
        CheckConstraint(
            "source_format IN ('docx','pdf','txt','markdown','fountain','srt','vtt')",
            name="ck_documents_source_format",
        ),
        CheckConstraint(
            "status IN ("
            "'uploading','verifying','ready','failed','cancelled','expired'"
            ")",
            name="ck_documents_status",
        ),
        CheckConstraint("declared_size_bytes > 0", name="ck_documents_declared_size"),
        CheckConstraint(
            "length(declared_sha256) = 64",
            name="ck_documents_declared_sha256_length",
        ),
        CheckConstraint("attempt >= 0", name="ck_documents_attempt"),
        CheckConstraint("version >= 0", name="ck_documents_version"),
        CheckConstraint(
            "detected_language IS NULL OR detected_language IN "
            "('zh-CN','en-US','mixed','unknown')",
            name="ck_documents_detected_language",
        ),
        CheckConstraint(
            "scene_count IS NULL OR scene_count >= 0", name="ck_documents_scene_count"
        ),
        CheckConstraint(
            "character_count IS NULL OR character_count > 0",
            name="ck_documents_character_count",
        ),
        CheckConstraint(
            "text_sha256 IS NULL OR length(text_sha256) = 64",
            name="ck_documents_text_sha256_length",
        ),
        CheckConstraint(
            "(status IN ('uploading','verifying') AND finished_at IS NULL) OR "
            "(status IN ('ready','failed','cancelled','expired') "
            "AND finished_at IS NOT NULL)",
            name="ck_documents_terminal_shape",
        ),
        CheckConstraint(
            "status <> 'ready' OR (detected_language IS NOT NULL "
            "AND scene_count IS NOT NULL AND character_count IS NOT NULL "
            "AND text_sha256 IS NOT NULL)",
            name="ck_documents_ready_shape",
        ),
        Index("ix_documents_owner_created", "owner_hash", "created_at"),
        Index("ix_documents_status_updated", "status", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(128), nullable=False)
    source_format: Mapped[str] = mapped_column(String(32), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    declared_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    declared_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    rights_statement_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="uploading")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detected_language: Mapped[str | None] = mapped_column(String(16))
    scene_count: Mapped[int | None] = mapped_column(Integer)
    character_count: Mapped[int | None] = mapped_column(Integer)
    text_sha256: Mapped[str | None] = mapped_column(String(64))
    quality_warnings: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class DocumentArtifactRow(Base):
    __tablename__ = "document_artifacts"
    __table_args__ = (
        UniqueConstraint("document_id", "kind", name="uq_document_artifacts_kind"),
        UniqueConstraint("bucket", "object_key", name="uq_document_artifacts_object"),
        CheckConstraint(
            "kind IN ('original','normalized')", name="ck_document_artifacts_kind"
        ),
        CheckConstraint(
            "status IN ('ready','deleting','deleted')",
            name="ck_document_artifacts_status",
        ),
        CheckConstraint("size_bytes > 0", name="ck_document_artifacts_size"),
        CheckConstraint(
            "length(sha256) = 64", name="ck_document_artifacts_sha256_length"
        ),
        CheckConstraint(
            "(status = 'deleted' AND deleted_at IS NOT NULL) OR "
            "(status <> 'deleted' AND deleted_at IS NULL)",
            name="ck_document_artifacts_deleted_shape",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ready")
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class AnalysisDocumentLockRow(Base):
    __tablename__ = "analysis_document_locks"
    __table_args__ = (Index("ix_analysis_document_locks_document", "document_id"),)

    job_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("analysis_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
