"""Independent, leased derivatives of verified download artifacts."""

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
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import JSON_DOCUMENT, Base, utc_now


class WatermarkTaskRow(Base):
    __tablename__ = "watermark_tasks"
    __table_args__ = (
        UniqueConstraint(
            "owner_hash", "idempotency_key", name="uq_watermark_idempotency"
        ),
        CheckConstraint(
            "status IN ('queued','running','succeeded','unchanged',"
            "'failed','cancelled')",
            name="ck_watermark_status",
        ),
        CheckConstraint("attempt >= 0", name="ck_watermark_attempt"),
        CheckConstraint("size_bytes >= 0", name="ck_watermark_size"),
        Index("ix_watermark_job_created", "job_id", "created_at"),
        Index(
            "uq_watermark_active_job",
            "job_id",
            unique=True,
            postgresql_where=text("status IN ('queued','running')"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("download_jobs.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False
    )
    engine: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="rapidocr-v4-sttn-e109b9dd",
        server_default="rapidocr-v4-sttn-e109b9dd",
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    object_key: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class WatermarkWorkerRow(Base):
    __tablename__ = "watermark_workers"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    engine: Mapped[str] = mapped_column(String(64), nullable=False)
