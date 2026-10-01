"""Durable preparation state before an existing download job is created."""

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
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import JSON_DOCUMENT, Base, utc_now
from app.models.execution_context import execution_context_check
from app.services.downloads.intent_models import (
    IntentStatus,
)

_INTENT_STATUS_SQL_VALUES = ", ".join(f"'{status.value}'" for status in IntentStatus)


class DownloadIntentRow(Base):
    __tablename__ = "download_intents"
    __table_args__ = (
        UniqueConstraint(
            "owner_hash", "idempotency_key", name="uq_download_intents_owner_key"
        ),
        UniqueConstraint("job_id", name="uq_download_intents_job"),
        CheckConstraint(
            f"status IN ({_INTENT_STATUS_SQL_VALUES})",
            name="ck_download_intents_status",
        ),
        CheckConstraint("mode = 'inspect'", name="ck_download_intents_mode"),
        CheckConstraint("version >= 0", name="ck_download_intents_version"),
        CheckConstraint("generation >= 0", name="ck_download_intents_generation"),
        CheckConstraint(
            execution_context_check("execution_context"),
            name="ck_download_intents_execution_context",
        ),
        CheckConstraint(
            f"status <> '{IntentStatus.READY.value}' OR inspection_id IS NOT NULL",
            name="ck_download_intents_result",
        ),
        CheckConstraint(
            f"status <> '{IntentStatus.HANDED_OFF.value}' OR job_id IS NOT NULL",
            name="ck_download_intents_handoff",
        ),
        Index("ix_download_intents_owner_created", "owner_hash", "created_at"),
        Index("ix_download_intents_deadline", "status", "deadline"),
        Index("uq_download_intents_inspection", "inspection_id", unique=True),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    url_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    url_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    url_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="inspect")
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=IntentStatus.QUEUED.value
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inspection_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("media_inspections.id")
    )
    job_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("download_jobs.id"))
    reason_code: Mapped[str | None] = mapped_column(String(64))
    execution_context: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True)
    )
    latest_failure: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
