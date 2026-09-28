"""Site session persistence.

``SiteSessionStates`` never selects the ciphertext and is the only reader the
API receives. ``SiteSessionSecrets`` belongs to the session broker and the seed
command; every write is conditional so late keepalives cannot overwrite a newer
import and nothing resurrects a revoked tombstone.
"""

from __future__ import annotations

from collections.abc import Set
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import case, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.site_session import SiteSessionRow as Row
from app.services.site_sessions import SiteSessionState, SiteSessionStatus

_STATUS_COLUMNS = (
    Row.site,
    Row.provider_key,
    Row.state,
    Row.seed_revision,
    Row.jar_version,
    Row.egress_route,
    Row.seeded_at,
    Row.refreshed_at,
    Row.verified_at,
    Row.last_error_code,
    Row.consecutive_failures,
    Row.state_changed_at,
    Row.next_check_at,
)


class SiteSessionConflict(Exception):
    """The record changed; the caller must reread before deciding again."""


@dataclass(frozen=True, slots=True)
class SiteSessionSecret:
    status: SiteSessionStatus
    ciphertext: bytes
    source_profile: str | None = None
    source_fingerprint: str | None = None


class SiteSessionStates:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, site: str) -> SiteSessionStatus | None:
        async with self._sessions() as session, session.begin():
            await _bounded(session)
            row = (
                await session.execute(select(*_STATUS_COLUMNS).where(Row.site == site))
            ).one_or_none()
        return None if row is None else _status(row._mapping)

    async def list(self) -> tuple[SiteSessionStatus, ...]:
        async with self._sessions() as session, session.begin():
            await _bounded(session)
            rows = (
                await session.execute(select(*_STATUS_COLUMNS).order_by(Row.site))
            ).all()
        return tuple(_status(row._mapping) for row in rows)


class SiteSessionSecrets:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def read(self, site: str) -> SiteSessionSecret | None:
        async with self._sessions() as session, session.begin():
            await _bounded(session)
            row = (
                await session.execute(
                    select(
                        *_STATUS_COLUMNS,
                        Row.ciphertext,
                        Row.source_profile,
                        Row.source_fingerprint,
                    ).where(Row.site == site)
                )
            ).one_or_none()
        if row is None or row.ciphertext is None:
            return None
        return SiteSessionSecret(
            _status(row._mapping),
            row.ciphertext,
            row.source_profile,
            row.source_fingerprint,
        )

    async def seed(
        self,
        site: str,
        *,
        provider_key: str | None,
        expected_seed_revision: int,
        ciphertext: bytes,
        egress_route: str,
        source_profile: str | None = None,
        source_fingerprint: str | None = None,
        automatic: bool = False,
    ) -> int:
        """Import a new identity; a revoked tombstone may be seeded again."""
        if expected_seed_revision < 0 or not ciphertext or not egress_route:
            raise ValueError("invalid site session seed")
        now = func.clock_timestamp()
        values: dict[str, Any] = dict(
            provider_key=provider_key,
            state=SiteSessionState.SEEDED.value,
            seed_revision=expected_seed_revision + 1,
            jar_version=0,
            ciphertext=ciphertext,
            source_profile=source_profile,
            source_fingerprint=source_fingerprint,
            egress_route=egress_route,
            seeded_at=now,
            refreshed_at=None,
            verified_at=None,
            next_check_at=None,
            last_error_code=None,
            consecutive_failures=0,
            state_changed_at=now,
        )
        if expected_seed_revision == 0:
            statement: Any = (
                insert(Row)
                .values(site=site, **values)
                .on_conflict_do_nothing()
                .returning(Row.seed_revision)
            )
        else:
            statement = (
                update(Row)
                .where(Row.site == site, Row.seed_revision == expected_seed_revision)
                .values(**values)
                .returning(Row.seed_revision)
            )
            if automatic:
                statement = statement.where(
                    Row.state == SiteSessionState.RESEED_REQUIRED.value,
                    Row.source_fingerprint.is_distinct_from(source_fingerprint),
                )
        return await self._write(statement)

    async def publish_jar(
        self,
        site: str,
        *,
        seed_revision: int,
        expected_jar_version: int,
        ciphertext: bytes,
    ) -> int:
        """Store cookies rotated by the session browser for the same identity."""
        if not ciphertext:
            raise ValueError("invalid site session jar")
        statement = (
            update(Row)
            .where(
                Row.site == site,
                Row.seed_revision == seed_revision,
                Row.jar_version == expected_jar_version,
                Row.state != SiteSessionState.REVOKED.value,
            )
            .values(
                ciphertext=ciphertext,
                jar_version=expected_jar_version + 1,
                refreshed_at=func.clock_timestamp(),
            )
            .returning(Row.jar_version)
        )
        return await self._write(statement)

    async def transition(
        self,
        site: str,
        *,
        seed_revision: int,
        allowed_from: Set[SiteSessionState],
        to: SiteSessionState,
        error_code: str | None = None,
        verified: bool = False,
        consecutive_failures: int = 0,
        next_check_at: datetime | None = None,
        reset_state_age: bool = False,
    ) -> None:
        """Conditionally move one import; staying in a state keeps its start time.

        ``state_changed_at`` marks entry into the current state so the degraded
        deadline counts from the first failure, not the latest one.
        """
        if to is SiteSessionState.REVOKED or SiteSessionState.REVOKED in allowed_from:
            raise ValueError("revocation has its own tombstone write")
        if consecutive_failures < 0:
            raise ValueError("failure count cannot be negative")
        now = func.clock_timestamp()
        values: dict[str, Any] = dict(
            state=to.value,
            next_check_at=next_check_at,
            last_error_code=error_code,
            consecutive_failures=consecutive_failures,
            state_changed_at=now
            if reset_state_age
            else case((Row.state == to.value, Row.state_changed_at), else_=now),
        )
        if verified:
            values["verified_at"] = now
        statement = (
            update(Row)
            .where(
                Row.site == site,
                Row.seed_revision == seed_revision,
                Row.state.in_([state.value for state in allowed_from]),
            )
            .values(**values)
            .returning(Row.seed_revision)
        )
        await self._write(statement)

    async def revoke(self, site: str, *, expected_seed_revision: int) -> None:
        statement = (
            update(Row)
            .where(
                Row.site == site,
                Row.seed_revision == expected_seed_revision,
                Row.state != SiteSessionState.REVOKED.value,
            )
            .values(
                state=SiteSessionState.REVOKED.value,
                ciphertext=None,
                state_changed_at=func.clock_timestamp(),
            )
            .returning(Row.seed_revision)
        )
        await self._write(statement)

    async def _write(self, statement: Any) -> int:
        async with self._sessions() as session, session.begin():
            await _bounded(session)
            await session.execute(text("SET LOCAL lock_timeout = '1s'"))
            result = await session.scalar(statement)
        if result is None:
            raise SiteSessionConflict("site session changed")
        return int(result)


async def _bounded(session: AsyncSession) -> None:
    await session.execute(text("SET LOCAL statement_timeout = '3s'"))


def _status(row: Any) -> SiteSessionStatus:
    return SiteSessionStatus(
        site=row["site"],
        provider_key=row["provider_key"],
        state=SiteSessionState(row["state"]),
        seed_revision=row["seed_revision"],
        jar_version=row["jar_version"],
        egress_route=row["egress_route"],
        seeded_at=row["seeded_at"],
        refreshed_at=row["refreshed_at"],
        verified_at=row["verified_at"],
        last_error_code=row["last_error_code"],
        consecutive_failures=row["consecutive_failures"],
        state_changed_at=row["state_changed_at"],
        next_check_at=row["next_check_at"],
    )
