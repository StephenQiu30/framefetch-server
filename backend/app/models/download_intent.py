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
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import JSON_DOCUMENT, Base, utc_now
from app.services.downloads.intent_models import (
    RUNNING_INTENT_STATUSES,
    IntentStatus,
)

_INTENT_STATUS_SQL_VALUES = ", ".join(f"'{status.value}'" for status in IntentStatus)
_RUNNING_INTENT_STATUS_SQL_VALUES = ", ".join(
    f"'{status.value}'" for status in RUNNING_INTENT_STATUSES
)


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
        CheckConstraint(
            "access_policy IN ('public','public_session',"
            "'operator_public','personal_entitled')",
            name="ck_download_intents_policy",
        ),
        CheckConstraint(
            "version >= 0 AND fence >= 0", name="ck_download_intents_version"
        ),
        CheckConstraint(
            "attempt >= 0 AND attempt <= max_attempts AND max_attempts BETWEEN 1 AND 3",
            name="ck_download_intents_attempt",
        ),
        CheckConstraint(
            "remaining_budget_ms BETWEEN 0 AND 180000",
            name="ck_download_intents_budget",
        ),
        CheckConstraint(
            f"(status IN ({_RUNNING_INTENT_STATUS_SQL_VALUES})) = "
            "(operation_id IS NOT NULL)",
            name="ck_download_intents_operation",
        ),
        CheckConstraint("generation >= 0", name="ck_download_intents_generation"),
        CheckConstraint(
            f"(status = '{IntentStatus.RETRY_WAIT.value}') = (retry_at IS NOT NULL)",
            name="ck_download_intents_retry",
        ),
        CheckConstraint(
            f"status <> '{IntentStatus.READY.value}' OR inspection_id IS NOT NULL",
            name="ck_download_intents_result",
        ),
        CheckConstraint(
            f"status <> '{IntentStatus.HANDED_OFF.value}' OR job_id IS NOT NULL",
            name="ck_download_intents_handoff",
        ),
        CheckConstraint(
            f"status <> '{IntentStatus.ACTION_REQUIRED.value}' "
            "OR (authorization_id IS NOT NULL "
            "AND authorization_deadline IS NOT NULL)",
            name="ck_download_intents_action",
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
    access_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=IntentStatus.QUEUED.value
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    remaining_budget_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=180000
    )
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    operation_id: Mapped[str | None] = mapped_column(String(128))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authorization_id: Mapped[UUID | None] = mapped_column(Uuid)
    authorization_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    inspection_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("media_inspections.id")
    )
    job_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("download_jobs.id"))
    reason_code: Mapped[str | None] = mapped_column(String(64))
    resolution_plan: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    next_strategy_id: Mapped[str | None] = mapped_column(String(128))
    selected_operation_id: Mapped[str | None] = mapped_column(String(64))
    latest_failure: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ResolutionAttemptRow(Base):
    __tablename__ = "resolution_attempts"
    __table_args__ = (
        UniqueConstraint(
            "intent_id", "generation", "attempt_no", name="uq_resolution_attempt_number"
        ),
        CheckConstraint(
            "generation >= 0 AND attempt_no BETWEEN 1 AND 3 AND fence > 0",
            name="ck_resolution_attempt_identity",
        ),
        CheckConstraint(
            "status IN ('started','succeeded','failed','abandoned','outcome_unknown')",
            name="ck_resolution_attempt_status",
        ),
        CheckConstraint(
            "(status = 'started') = (finished_at IS NULL)",
            name="ck_resolution_attempt_finished",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms BETWEEN 0 AND 180000",
            name="ck_resolution_attempt_duration",
        ),
        CheckConstraint(
            "status <> 'succeeded' OR inspection_id IS NOT NULL",
            name="ck_resolution_attempt_result",
        ),
        Index("ix_resolution_attempt_intent_started", "intent_id", "started_at"),
    )

    operation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    intent_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("download_intents.id", ondelete="CASCADE"), nullable=False
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    fence: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy_id: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    context_key: Mapped[str] = mapped_column(String(64), nullable=False)
    access_context: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, nullable=False
    )
    runner_instance_id: Mapped[str] = mapped_column(String(32), nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    failure: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    evidence_signature: Mapped[str | None] = mapped_column(String(64))
    inspection_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("media_inspections.id")
    )
