"""Deployment-owned site sessions; only the session broker reads the ciphertext."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SiteSessionRow(Base):
    __tablename__ = "site_sessions"
    __table_args__ = (
        CheckConstraint(
            "state IN ('seeded', 'verifying', 'ready', 'degraded', "
            "'reseed_required', 'revoked')",
            name="ck_site_sessions_state",
        ),
        CheckConstraint("seed_revision > 0", name="ck_site_sessions_seed_revision"),
        CheckConstraint("jar_version >= 0", name="ck_site_sessions_jar_version"),
        CheckConstraint(
            "(state = 'revoked') = (ciphertext IS NULL)",
            name="ck_site_sessions_revoked",
        ),
    )

    site: Mapped[str] = mapped_column(String(253), primary_key=True)
    provider_key: Mapped[str | None] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    seed_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    jar_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    egress_route: Mapped[str] = mapped_column(String(64), nullable=False)
    seeded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    state_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
