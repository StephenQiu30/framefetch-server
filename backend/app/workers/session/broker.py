"""The session broker: sole key holder, lifecycle owner and lease issuer.

It never talks to the Internet. It hands imported jars to the session browser,
stores the cookies the browser rotates, moves each site through the lifecycle
in ``site_session_lifecycle`` and seals one-task leases for Runners.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.security.site_session_cipher import SiteSessionCipher
from app.repositories.providers.site_sessions import (
    SiteSessionConflict,
    SiteSessionSecret,
    SiteSessionSecrets,
    SiteSessionStates,
)
from app.services.site_session_lifecycle import (
    SessionEvent,
    SessionTransition,
    decide,
    execution_event,
    expire,
)
from app.services.site_sessions import (
    SiteSessionState,
    SiteSessionStatus,
    site_policy,
)
from app.workers.session.browser_client import (
    BrowserReport,
    BrowserUnavailable,
    SessionBrowser,
)
from app.workers.session.contracts import BrowserOutcome, lease_associated_data
from app.workers.session.sealing import SealError, seal

_logger = logging.getLogger(__name__)
_EVENTS = {
    BrowserOutcome.VERIFIED: SessionEvent.VERIFIED,
    BrowserOutcome.LOGGED_OUT: SessionEvent.LOGGED_OUT,
    BrowserOutcome.AUTH_FAILURE: SessionEvent.AUTH_FAILURE,
}
_LIVE = frozenset(
    {
        SiteSessionState.SEEDED,
        SiteSessionState.VERIFYING,
        SiteSessionState.READY,
        SiteSessionState.DEGRADED,
    }
)


class SessionNotReady(Exception):
    """No executable session for this site and import revision."""


@dataclass(frozen=True, slots=True)
class LeaseGrant:
    site: str
    seed_revision: int
    jar_version: int
    expires_at: int
    jar: bytes
    headers: bytes | None


class SessionBroker:
    def __init__(
        self,
        *,
        states: SiteSessionStates,
        secrets: SiteSessionSecrets,
        cipher: SiteSessionCipher,
        browser: SessionBrowser,
        lease_seconds: int = 600,
        keepalive_seconds: int = 1800,
        keepalive_jitter_seconds: int = 300,
        concurrency: int = 2,
        clock: Callable[[], datetime] | None = None,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        if lease_seconds <= 0 or keepalive_seconds <= keepalive_jitter_seconds:
            raise ValueError("invalid site session broker timing")
        self._states, self._secrets = states, secrets
        self._cipher, self._browser = cipher, browser
        self._lease = timedelta(seconds=lease_seconds)
        self._keepalive_seconds = keepalive_seconds
        self._jitter_range = keepalive_jitter_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._jitter = jitter
        self._slots = asyncio.Semaphore(concurrency)
        self._locks: dict[str, asyncio.Lock] = {}
        self._due: dict[tuple[str, int], datetime] = {}
        self._forgotten: set[tuple[str, int]] = set()

    # Scheduling -------------------------------------------------------------

    async def scan(self) -> None:
        now = self._clock()
        work = []
        for status in await self._states.list():
            key = (status.site, status.seed_revision)
            if status.state is SiteSessionState.REVOKED:
                if key not in self._forgotten:
                    work.append(self._forget(status))
            elif (expired := expire(status, now=now)) is not None:
                await self._apply(status, expired)
            elif status.state in {SiteSessionState.SEEDED, SiteSessionState.VERIFYING}:
                work.append(self._bootstrap(status.site, status.seed_revision))
            elif status.state in {SiteSessionState.READY, SiteSessionState.DEGRADED}:
                if now >= self._due.setdefault(key, self._first_due(status)):
                    work.append(self._keepalive(status.site, status.seed_revision))
        await asyncio.gather(*(self._bounded(item) for item in work))

    async def _bounded(self, work: object) -> None:
        async with self._slots:
            try:
                await work  # type: ignore[misc]
            except Exception:
                # One site's failure must never stop the scan for other sites.
                _logger.exception("site session maintenance failed")

    def _first_due(self, status: SiteSessionStatus) -> datetime:
        base = max(
            value
            for value in (status.seeded_at, status.verified_at, status.refreshed_at)
            if value is not None
        )
        return base + self._interval()

    def _interval(self) -> timedelta:
        spread = self._jitter(-self._jitter_range, self._jitter_range)
        return timedelta(seconds=self._keepalive_seconds + spread)

    def _lock(self, site: str) -> asyncio.Lock:
        return self._locks.setdefault(site, asyncio.Lock())

    # Browser maintenance ----------------------------------------------------

    async def _bootstrap(self, site: str, seed_revision: int) -> None:
        async with self._lock(site):
            secret = await self._current(site, seed_revision)
            if secret is None:
                return
            if secret.status.state is SiteSessionState.SEEDED:
                try:
                    await self._secrets.transition(
                        site,
                        seed_revision=seed_revision,
                        allowed_from={SiteSessionState.SEEDED},
                        to=SiteSessionState.VERIFYING,
                    )
                except SiteSessionConflict:
                    return
            await self._load_into_browser(secret)

    async def _keepalive(self, site: str, seed_revision: int) -> None:
        async with self._lock(site):
            self._due[(site, seed_revision)] = self._clock() + self._interval()
            secret = await self._current(site, seed_revision)
            if secret is None:
                return
            try:
                report = await self._browser.keepalive(site, seed_revision)
            except BrowserUnavailable:
                _logger.warning("session browser unavailable for keepalive: %s", site)
                return
            if report.outcome is BrowserOutcome.PROFILE_MISSING:
                # A lost browser volume is rebuilt from the latest stored jar.
                await self._load_into_browser(secret)
                return
            await self._absorb(secret, self._decrypt(secret), report)

    async def _load_into_browser(self, secret: SiteSessionSecret) -> None:
        status = secret.status
        jar = self._decrypt(secret)
        if jar is None:
            await self._apply(
                status,
                SessionTransition(
                    _LIVE,
                    SiteSessionState.RESEED_REQUIRED,
                    status.consecutive_failures,
                    "session_undecryptable",
                ),
            )
            return
        try:
            report = await self._browser.bootstrap(
                status.site, status.seed_revision, jar
            )
        except BrowserUnavailable:
            _logger.warning(
                "session browser unavailable for bootstrap: %s", status.site
            )
            return
        await self._absorb(secret, jar, report)

    async def _absorb(
        self,
        secret: SiteSessionSecret,
        current_jar: bytes | None,
        report: BrowserReport,
    ) -> None:
        status = secret.status
        if (
            report.outcome is BrowserOutcome.VERIFIED
            and report.jar is not None
            and report.jar != current_jar
        ):
            version = status.jar_version + 1
            try:
                await self._secrets.publish_jar(
                    status.site,
                    seed_revision=status.seed_revision,
                    expected_jar_version=status.jar_version,
                    ciphertext=self._cipher.encrypt(
                        status.site, status.seed_revision, version, report.jar
                    ),
                )
            except SiteSessionConflict:
                pass
        event = _EVENTS.get(report.outcome)
        if event is None:
            return
        latest = await self._states.get(status.site)
        if latest is None or latest.seed_revision != status.seed_revision:
            return
        await self._apply(latest, decide(latest, event, error_code=report.error_code))

    async def _forget(self, status: SiteSessionStatus) -> None:
        try:
            await self._browser.forget(status.site)
        except BrowserUnavailable:
            return
        self._forgotten.add((status.site, status.seed_revision))

    # State ------------------------------------------------------------------

    async def _apply(
        self, status: SiteSessionStatus, transition: SessionTransition | None
    ) -> None:
        if transition is None:
            return
        try:
            await self._secrets.transition(
                status.site,
                seed_revision=status.seed_revision,
                allowed_from=transition.allowed_from,
                to=transition.to,
                error_code=transition.error_code,
                verified=transition.verified,
                consecutive_failures=transition.consecutive_failures,
            )
        except SiteSessionConflict:
            return
        key = (status.site, status.seed_revision)
        if transition.to is SiteSessionState.DEGRADED:
            # Re-verify at the next scan instead of waiting a full interval.
            self._due[key] = self._clock()
        if transition.requires_reseed and status.state is not transition.to:
            # The conditional write has exactly one winner, so this is the single
            # alert for this import. The admin status page shows the same state.
            _logger.warning(
                "site session requires re-import: site=%s revision=%s reason=%s",
                status.site,
                status.seed_revision,
                transition.error_code,
            )

    async def _current(self, site: str, seed_revision: int) -> SiteSessionSecret | None:
        secret = await self._secrets.read(site)
        if (
            secret is None
            or secret.status.seed_revision != seed_revision
            or secret.status.state not in _LIVE
        ):
            return None
        return secret

    def _decrypt(self, secret: SiteSessionSecret) -> bytes | None:
        status = secret.status
        try:
            return self._cipher.decrypt(
                status.site, status.seed_revision, status.jar_version, secret.ciphertext
            )
        except ValueError:
            return None

    # Runner RPC -------------------------------------------------------------

    async def lease(
        self, *, task_id: str, site: str, seed_revision: int, runner_key: bytes
    ) -> LeaseGrant:
        secret = await self._secrets.read(site)
        if (
            secret is None
            or secret.status.state is not SiteSessionState.READY
            or secret.status.seed_revision != seed_revision
        ):
            raise SessionNotReady(site)
        jar = self._decrypt(secret)
        if jar is None:
            raise SessionNotReady(site)
        expires_at = int((self._clock() + self._lease).timestamp())
        status = secret.status
        try:
            sealed = seal(
                jar,
                runner_key,
                associated_data=lease_associated_data(
                    "jar", task_id, site, seed_revision, expires_at
                ),
            )
        except SealError as exc:
            raise ValueError("invalid Runner key") from exc
        headers = None
        if site_policy(site).header_plugin is not None:
            try:
                headers = await self._browser.headers(
                    site,
                    seed_revision,
                    task_id=task_id,
                    expires_at=expires_at,
                    runner_key=runner_key,
                )
            except BrowserUnavailable as exc:
                raise SessionNotReady(site) from exc
        return LeaseGrant(
            site, seed_revision, status.jar_version, expires_at, sealed, headers
        )

    async def report_failure(
        self, *, site: str, seed_revision: int, error_code: str
    ) -> None:
        event = execution_event(error_code)
        if event is None:
            return
        status = await self._states.get(site)
        if status is None or status.seed_revision != seed_revision:
            return
        await self._apply(status, decide(status, event, error_code=error_code))
