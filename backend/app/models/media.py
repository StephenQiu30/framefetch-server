"""Persistence rows for short-lived media inspections and semantic formats."""

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
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import JSON_DOCUMENT, Base, utc_now
from app.models.execution_context import execution_context_check


class MediaInspectionRow(Base):
    __tablename__ = "media_inspections"
    __table_args__ = (
        UniqueConstraint(
            "owner_hash",
            "idempotency_key",
            name="uq_media_inspections_owner_idempotency",
        ),
        CheckConstraint("duration_seconds >= 0", name="ck_inspection_duration"),
        CheckConstraint(
            execution_context_check("(metadata->'execution_context')"),
            name="ck_media_inspections_execution_context",
        ),
        Index("ix_media_inspections_owner_expires", "owner_hash", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    url_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    url_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    url_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    extractor_key: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_media_id: Mapped[str] = mapped_column(String(256), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_DOCUMENT, nullable=False, default=dict
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class MediaFormatRow(Base):
    __tablename__ = "media_formats"
    __table_args__ = (
        UniqueConstraint(
            "inspection_id",
            "plan_fingerprint",
            name="uq_media_formats_inspection_plan",
        ),
        Index("ix_media_formats_inspection", "inspection_id"),
        Index("ix_media_formats_expires", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    inspection_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("media_inspections.id", ondelete="CASCADE"),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    semantic_plan: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    provider_hints: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class MediaThumbnailRow(Base):
    __tablename__ = "media_thumbnails"
    __table_args__ = (
        UniqueConstraint("bucket", "object_key", name="uq_media_thumbnails_object"),
        CheckConstraint("size_bytes > 0", name="ck_media_thumbnails_size"),
        CheckConstraint(
            "length(sha256) = 64", name="ck_media_thumbnails_sha256_length"
        ),
        CheckConstraint(
            "content_type IN ('image/avif','image/jpeg','image/png','image/webp')",
            name="ck_media_thumbnails_content_type",
        ),
    )

    inspection_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("media_inspections.id", ondelete="CASCADE"),
        primary_key=True,
    )
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class DownloadThumbnailRow(Base):
    __tablename__ = "download_thumbnails"
    __table_args__ = (
        UniqueConstraint("bucket", "object_key", name="uq_download_thumbnails_object"),
        CheckConstraint("size_bytes > 0", name="ck_download_thumbnails_size"),
        CheckConstraint(
            "length(sha256) = 64", name="ck_download_thumbnails_sha256_length"
        ),
        CheckConstraint(
            "content_type IN ('image/avif','image/jpeg','image/png','image/webp')",
            name="ck_download_thumbnails_content_type",
        ),
    )

    job_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("download_jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
