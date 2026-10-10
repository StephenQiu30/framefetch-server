"""Append-only admission ledger; resource deletion cannot refund daily usage."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ResourceAdmissionRow(Base):
    __tablename__ = "resource_admissions"
    __table_args__ = (
        CheckConstraint("reserved_bytes >= 0", name="ck_admissions_bytes"),
        CheckConstraint("analysis_attempts >= 0", name="ck_admissions_attempts"),
        CheckConstraint(
            "kind IN ('download','media_import','document_import',"
            "'analysis','inspection','watermark')",
            name="ck_admissions_kind",
        ),
        Index("ix_admissions_owner_created", "owner_hash", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    analysis_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
