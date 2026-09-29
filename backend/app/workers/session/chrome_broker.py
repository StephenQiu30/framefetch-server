"""Container broker that relays the operator's live Chrome login state.

The Runner contract (status, sealed one-task leases, rotation, failures) is
unchanged. Instead of a database copy kept alive by a second browser, every
lease is read fresh from the host Chrome agent, so the platform only ever sees
one client for the session and there is nothing to keep alive or re-import.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.integrations.site_session_catalog import site_target
from app.services.site_sessions import InvalidSessionSite
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_session_files import validated_cookie_payload
from app.workers.session.chrome_agent import (
    COOKIES_PATH,
    CookiesRequest,
    CookiesResponse,
    cookies_associated_data,
)
from app.workers.session.contracts import lease_associated_data
from app.workers.session.rpc import RpcError, SignedClient
from app.workers.session.sealing import (
    SealError,
    decode,
    encode,
    open_sealed,
    public_key,
    seal,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

# Chrome is the only session; its identity never changes under a Runner.
LIVE_REVISION = 1


class SessionNotReady(Exception):
    """The host agent cannot be reached or cannot read Chrome right now."""


class SessionLoginRequired(Exception):
    """Chrome has no usable login for this site; only the operator can fix it."""


@dataclass(frozen=True, slots=True)
class LeaseGrant:
    site: str
    seed_revision: int
    jar_version: int
    expires_at: int
    jar: bytes
    headers: bytes | None
    rotation_key: bytes


class ChromeSessionBroker:
    def __init__(self, agent: SignedClient, *, lease_seconds: int) -> None:
        self._agent = agent
        self._lease_seconds = lease_seconds

    async def scan(self) -> None:
        """Nothing to keep alive: the operator's Chrome does that."""

    async def warming_up(self) -> bool:
        return False

    async def ready_revision(self, site: str) -> int:
        await self._payload(site)
        return LIVE_REVISION

    async def lease(
        self, *, task_id: str, site: str, seed_revision: int, runner_key: bytes
    ) -> LeaseGrant:
        if seed_revision != LIVE_REVISION:
            raise SessionNotReady(site)
        payload = await self._payload(site)
        expires_at = int(time.time()) + self._lease_seconds
        jar = seal(
            payload,
            runner_key,
            associated_data=lease_associated_data(
                "jar", task_id, site, seed_revision, expires_at
            ),
        )
        # Runner-side rotations are dropped: Chrome stays the source of truth.
        discard = public_key(X25519PrivateKey.generate())
        return LeaseGrant(site, seed_revision, 0, expires_at, jar, None, discard)

    async def absorb_rotation(self, **_: object) -> None:
        return None

    async def report_failure(self, **_: object) -> None:
        return None

    async def _payload(self, site: str) -> bytes:
        try:
            target = site_target(site)
        except InvalidSessionSite:
            raise SessionLoginRequired(site) from None
        key = X25519PrivateKey.generate()
        try:
            reply = await self._agent.post(
                COOKIES_PATH,
                CookiesRequest(site=site, public_key=encode(public_key(key))),
                CookiesResponse,
            )
            opened = open_sealed(
                decode(reply.jar),
                key,
                associated_data=cookies_associated_data(site),
            )
            return validated_cookie_payload(opened, target.cookie_domains)
        except RpcError as exc:
            if exc.code in {"credential_required", "chrome_profile_ambiguous"}:
                raise SessionLoginRequired(site) from None
            raise SessionNotReady(site) from None
        except (SealError, RunnerFailure, ValueError):
            raise SessionNotReady(site) from None
