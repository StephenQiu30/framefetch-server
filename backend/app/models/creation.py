"""PostgreSQL facts for immutable materials, human revisions and content tasks."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
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


class CreationProjectRow(Base):
    __tablename__ = "creation_projects"
    __table_args__ = (
        UniqueConstraint(
            "owner_hash", "idempotency_key", name="uq_creation_project_key"
        ),
        Index("ix_creation_projects_owner", "owner_hash", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class CreationMaterialRow(Base):
    __tablename__ = "creation_materials"
    __table_args__ = (
        UniqueConstraint(
            "owner_hash", "idempotency_key", name="uq_creation_material_key"
        ),
        CheckConstraint(
            "kind IN ('text','screenplay','video','subtitle','image','reference')",
            name="ck_creation_material_kind",
        ),
        CheckConstraint(
            "binary_data IS NULL OR octet_length(binary_data) <= 10485760",
            name="ck_creation_material_bytes",
        ),
        Index("ix_creation_materials_owner", "owner_hash", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("creation_projects.id", ondelete="RESTRICT")
    )
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    rights_statement: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("artifacts.id", ondelete="RESTRICT")
    )
    document_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="RESTRICT")
    )
    source_url: Mapped[str | None] = mapped_column(String(2048))
    source_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "creation_revisions.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_creation_material_source_revision",
        ),
    )
    binary_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    current_revision_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class CreationTaskRow(Base):
    __tablename__ = "creation_tasks"
    __table_args__ = (
        UniqueConstraint("owner_hash", "idempotency_key", name="uq_creation_task_key"),
        CheckConstraint(
            "status IN ('queued','processing','awaiting_confirmation',"
            "'completed','failed','cancelled','outcome_unknown')",
            name="ck_creation_task_status",
        ),
        CheckConstraint("attempt > 0", name="ck_creation_task_attempt"),
        Index("ix_creation_tasks_owner", "owner_hash", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("creation_projects.id", ondelete="RESTRICT")
    )
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    skill_id: Mapped[str] = mapped_column(String(128), nullable=False)
    method_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    material_revision_ids: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, nullable=False
    )
    options: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    budget: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    output_language: Mapped[str] = mapped_column(String(35), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    current_revision_id: Mapped[UUID | None] = mapped_column(Uuid)
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    limitations: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    worker_id: Mapped[str | None] = mapped_column(String(128))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class CreationRevisionRow(Base):
    __tablename__ = "creation_revisions"
    __table_args__ = (
        CheckConstraint(
            "(material_id IS NULL) <> (task_id IS NULL)",
            name="ck_creation_revision_parent",
        ),
        CheckConstraint("number > 0", name="ck_creation_revision_number"),
        CheckConstraint("length(sha256) = 64", name="ck_creation_revision_sha"),
        UniqueConstraint("material_id", "number", name="uq_creation_material_revision"),
        UniqueConstraint("task_id", "number", name="uq_creation_task_revision"),
        UniqueConstraint(
            "owner_hash", "idempotency_key", name="uq_creation_revision_key"
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    material_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("creation_materials.id", ondelete="RESTRICT")
    )
    task_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("creation_tasks.id", ondelete="RESTRICT")
    )
    parent_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("creation_revisions.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    request_sha256: Mapped[str | None] = mapped_column(String(64))
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class CreationExportRow(Base):
    __tablename__ = "creation_exports"
    __table_args__ = (
        UniqueConstraint(
            "revision_id", "format", name="uq_creation_export_revision_format"
        ),
        CheckConstraint(
            "octet_length(binary_data) BETWEEN 1 AND 67108864",
            name="ck_creation_export_bytes",
        ),
        CheckConstraint("length(sha256) = 64", name="ck_creation_export_sha"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("creation_tasks.id", ondelete="RESTRICT"), nullable=False
    )
    revision_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("creation_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    binary_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    export_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_DOCUMENT, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
