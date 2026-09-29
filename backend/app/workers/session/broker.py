"""The session broker: sole key holder, lifecycle owner and lease issuer.

It never talks to the Internet. It hands imported jars to the session browser,
stores the cookies the browser rotates, moves each site through the lifecycle
in ``site_session_lifecycle`` and seals one-task leases for Runners.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.security.site_session_cipher import SiteSessionCipher
from app.integrations.site_session_catalog import site_target
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
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_credential_lease import (
    ProviderCredentialLeaseCoordinator,
)
from app.workers.runner.provider_session_files import validated_cookie_payload
from app.workers.session.browser_client import (
    BrowserReport,
    BrowserUnavailable,
    SessionBrowser,
)
from app.workers.session.contracts import BrowserOutcome, lease_associated_data
from app.workers.session.sealing import SealError, open_sealed, public_key, seal
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

_logger = logging.getLogger(__name__)
_EVENTS = {
    BrowserOutcome.VERIFIED: SessionEvent.VERIFIED,
    BrowserOutcome.LOGGED_OUT: SessionEvent.LOGGED_OUT,
    BrowserOutcome.AUTH_FAILURE: SessionEvent.AUTH_FAILURE,
    BrowserOutcome.TEMPORARY_FAILURE: SessionEvent.TEMPORARY_FAILURE,
    BrowserOutcome.UNAVAILABLE: SessionEvent.TEMPORARY_FAILURE,
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
    rotation_key: bytes


@dataclass(frozen=True, slots=True)
class PendingRotation:
    site: str
    seed_revision: int
    jar_version: int
    expires_at: int
    key: X25519PrivateKey
    browser_epoch: str | None
    return_until: int


class SessionBroker:
    def __init__(
        self,
        *,
        states: SiteSessionStates,
        secrets: SiteSessionSecrets,
        cipher: SiteSessionCipher,
        browser: SessionBrowser,
        coordinator: ProviderCredentialLeaseCoordinator,
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
        self._coordinator = coordinator
        self._lease = timedelta(seconds=lease_seconds)
        self._keepalive_seconds = keepalive_seconds
        self._jitter_range = keepalive_jitter_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._jitter = jitter
        self._slots = asyncio.Semaphore(concurrency)
        self._locks: dict[str, asyncio.Lock] = {}
        self._due: dict[tuple[str, int], datetime] = {}
        self._forgotten: set[tuple[str, int]] = set()
        self._verified: set[tuple[str, int]] = set()
        self._browser_epoch: str | None = None
        self._pending_rotations: dict[str, PendingRotation] = {}

    # Scheduling -------------------------------------------------------------

    async def scan(self) -> None:
        await self._check_browser_epoch()
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
                if now >= self._due.setdefault(key, status.next_check_at or now):
                    work.append(self._bootstrap(status.site, status.seed_revision))
            elif status.state in {SiteSessionState.READY, SiteSessionState.DEGRADED}:
                if now >= self._due.setdefault(
                    key,
                    (status.next_check_at or now)
                    if status.state is SiteSessionState.DEGRADED
                    else now,
                ):
                    work.append(self._keepalive(status.site, status.seed_revision))
        await asyncio.gather(*(self._bounded(item) for item in work))

    async def _bounded(self, work: object) -> None:
        async with self._slots:
            try:
                await work  # type: ignore[misc]
            except RunnerFailure:
                # Active media owns the shared site lock; retry next scan.
                return
            except Exception:
                # One site's failure must never stop the scan for other sites.
                _logger.exception("site session maintenance failed")

    async def _check_browser_epoch(self) -> None:
        try:
            epoch = await self._browser.identity()
        except BrowserUnavailable:
            self._verified.clear()
            self._browser_epoch = None
            raise SessionNotReady("browser_unavailable") from None
        if epoch != self._browser_epoch:
            self._verified.clear()
            self._due.clear()
            self._browser_epoch = epoch

    def _interval(self) -> timedelta:
        spread = self._jitter(0, self._jitter_range)
        return timedelta(seconds=self._keepalive_seconds + spread)

    @asynccontextmanager
    async def _lock(self, site: str) -> AsyncIterator[None]:
        # Admission survives a healthy maintenance pass: clearing it up front made
        # every site unusable for the length of each keepalive. It is withdrawn
        # only when the pass fails or ends without a fresh verification.
        async with self._locks.setdefault(site, asyncio.Lock()):
            async with self._coordinator.hold(site, "session"):
                try:
                    yield
                except BaseException:
                    self._withdraw(site)
                    raise

    def _withdraw(self, site: str) -> None:
        self._verified = {key for key in self._verified if key[0] != site}

    # Browser maintenance ----------------------------------------------------

    async def _bootstrap(self, site: str, seed_revision: int) -> None:
        async with self._lock(site):
            secret = await self._current(site, seed_revision)
            if secret is None:
                return
            if secret.status.state is SiteSessionState.SEEDED:
                # A new identity must not inherit old localStorage or service workers.
                await self._browser.forget(site)
                try:
                    await self._secrets.transition(
                        site,
                        seed_revision=seed_revision,
                        allowed_from={SiteSessionState.SEEDED},
                        to=SiteSessionState.VERIFYING,
                    )
                except SiteSessionConflict:
                    return
            secret = await self._current(site, seed_revision)
            if secret is None:
                return
            self._due[(site, seed_revision)] = self._clock() + timedelta(seconds=60)
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
                await self._apply(
                    secret.status,
                    decide(
                        secret.status,
                        SessionEvent.TEMPORARY_FAILURE,
                        error_code="browser_unavailable",
                    ),
                )
                return
            if report.outcome is BrowserOutcome.PROFILE_MISSING:
                # A lost browser volume is rebuilt from the latest stored jar.
                self._withdraw(site)
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
            await self._apply(
                status,
                decide(
                    status,
                    SessionEvent.TEMPORARY_FAILURE,
                    error_code="browser_unavailable",
                ),
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
                self._verified.discard((status.site, status.seed_revision))
                return
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
        key = (status.site, status.seed_revision)
        due = None
        if transition.verified:
            due = self._clock() + self._interval()
        elif transition.to is SiteSessionState.DEGRADED:
            age = (
                max(0, (self._clock() - status.state_changed_at).total_seconds())
                if status.state is SiteSessionState.DEGRADED
                else 0
            )
            delay = min(1800, 60 * 2 ** min(5, int(age / 60)))
            if transition.error_code == "provider_rate_limited":
                delay = max(300, delay)
            due = self._clock() + timedelta(seconds=delay)
        try:
            await self._secrets.transition(
                status.site,
                seed_revision=status.seed_revision,
                allowed_from=transition.allowed_from,
                to=transition.to,
                error_code=transition.error_code,
                verified=transition.verified,
                consecutive_failures=transition.consecutive_failures,
                next_check_at=due,
                reset_state_age=(
                    transition.consecutive_failures > 0
                    and status.consecutive_failures == 0
                ),
            )
        except SiteSessionConflict:
            return
        if due is not None:
            self._due[key] = due
        if transition.verified:
            self._verified.add(key)
        else:
            self._verified.discard(key)
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

    async def warming_up(self) -> bool:
        """True while a session stored as ready has not been verified live yet."""
        return any(
            status.state is SiteSessionState.READY
            and (status.site, status.seed_revision) not in self._verified
            for status in await self._states.list()
        )

    # Runner RPC -------------------------------------------------------------

    async def ready_revision(self, site: str) -> int:
        """The import revision a new access context must freeze."""
        await self._check_browser_epoch()
        status = await self._states.get(site)
        if (
            status is None
            or status.state is not SiteSessionState.READY
            or (site, status.seed_revision) not in self._verified
        ):
            raise SessionNotReady(site)
        return status.seed_revision

    async def lease(
        self, *, task_id: str, site: str, seed_revision: int, runner_key: bytes
    ) -> LeaseGrant:
        await self._check_browser_epoch()
        secret = await self._secrets.read(site)
        if (
            secret is None
            or secret.status.state is not SiteSessionState.READY
            or secret.status.seed_revision != seed_revision
            or (site, seed_revision) not in self._verified
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
        now = int(self._clock().timestamp())
        self._pending_rotations = {
            key: value
            for key, value in self._pending_rotations.items()
            if value.return_until > now
        }
        if task_id in self._pending_rotations or len(self._pending_rotations) >= 1024:
            raise SessionNotReady(site)
        rotation_key = X25519PrivateKey.generate()
        self._pending_rotations[task_id] = PendingRotation(
            site,
            seed_revision,
            status.jar_version,
            expires_at,
            rotation_key,
            self._browser_epoch,
            int((self._clock() + timedelta(seconds=7500)).timestamp()),
        )
        return LeaseGrant(
            site,
            seed_revision,
            status.jar_version,
            expires_at,
            sealed,
            headers,
            public_key(rotation_key),
        )

    async def absorb_rotation(
        self, *, task_id: str, site: str, seed_revision: int, sealed_jar: bytes
    ) -> None:
        # The Runner still holds the distributed site lock. A lease can publish
        # once, only to the original import, jar version and browser process.
        pending = self._pending_rotations.pop(task_id, None)
        if (
            pending is None
            or pending.site != site
            or pending.seed_revision != seed_revision
            or pending.return_until <= self._clock().timestamp()
        ):
            raise SessionNotReady(site)
        await self._check_browser_epoch()
        if pending.browser_epoch != self._browser_epoch:
            raise SessionNotReady(site)
        secret = await self._current(site, seed_revision)
        if secret is None or secret.status.jar_version != pending.jar_version:
            raise SessionNotReady(site)
        try:
            jar = open_sealed(
                sealed_jar,
                pending.key,
                associated_data=lease_associated_data(
                    "rotation", task_id, site, seed_revision, pending.expires_at
                ),
            )
            jar = validated_cookie_payload(jar, site_target(site).cookie_domains)
        except (SealError, RunnerFailure) as exc:
            raise SessionNotReady(site) from exc
        if jar == self._decrypt(secret):
            return
        self._verified.discard((site, seed_revision))
        try:
            report = await self._browser.bootstrap(site, seed_revision, jar)
        except BrowserUnavailable:
            await self._apply(
                secret.status,
                decide(
                    secret.status,
                    SessionEvent.TEMPORARY_FAILURE,
                    error_code="browser_unavailable",
                ),
            )
            raise SessionNotReady(site) from None
        await self._absorb(secret, self._decrypt(secret), report)
        if report.outcome is not BrowserOutcome.VERIFIED:
            raise SessionNotReady(site)

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
