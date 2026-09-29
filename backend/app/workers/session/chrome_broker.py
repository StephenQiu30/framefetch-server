"""Container broker that relays the operator's live Chrome login state.

The broker reads the host source on demand and seals one-task leases for
Runners. It does not own persistent sessions or accept Cookie writeback.
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
    headers_associated_data,
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

# Transport revision for the live source, not proof of account identity.
LIVE_REVISION = 1


class SessionNotReady(Exception):
    """The host agent cannot be reached or cannot read Chrome right now."""


class SessionLoginRequired(Exception):
    """Chrome has no usable login for this site; only the operator can fix it."""


@dataclass(frozen=True, slots=True)
class LeaseGrant:
    site: str
    seed_revision: int
    expires_at: int
    jar: bytes
    headers: bytes | None


class ChromeSessionBroker:
    def __init__(self, agent: SignedClient, *, lease_seconds: int) -> None:
        self._agent = agent
        self._lease_seconds = lease_seconds

    async def ready_revision(self, site: str) -> int:
        await self._read(site, include_headers=False)
        return LIVE_REVISION

    async def lease(
        self, *, task_id: str, site: str, seed_revision: int, runner_key: bytes
    ) -> LeaseGrant:
        if seed_revision != LIVE_REVISION:
            raise SessionNotReady(site)
        payload, headers = await self._read(site, include_headers=True)
        expires_at = int(time.time()) + self._lease_seconds

        def sealed(kind: str, value: bytes) -> bytes:
            return seal(
                value,
                runner_key,
                associated_data=lease_associated_data(
                    kind, task_id, site, seed_revision, expires_at
                ),
            )

        return LeaseGrant(
            site,
            seed_revision,
            expires_at,
            sealed("jar", payload),
            None if headers is None else sealed("headers", headers),
        )

    async def _read(
        self, site: str, *, include_headers: bool
    ) -> tuple[bytes, bytes | None]:
        try:
            target = site_target(site)
        except InvalidSessionSite:
            raise SessionLoginRequired(site) from None
        key = X25519PrivateKey.generate()
        try:
            reply = await self._agent.post(
                COOKIES_PATH,
                CookiesRequest(
                    site=site,
                    public_key=encode(public_key(key)),
                    include_headers=include_headers,
                ),
                CookiesResponse,
            )
            opened = open_sealed(
                decode(reply.jar),
                key,
                associated_data=cookies_associated_data(site),
            )
            headers = (
                None
                if reply.headers is None
                else open_sealed(
                    decode(reply.headers),
                    key,
                    associated_data=headers_associated_data(site),
                )
            )
            return validated_cookie_payload(opened, target.cookie_domains), headers
        except RpcError as exc:
            if exc.code in {"credential_required", "chrome_profile_ambiguous"}:
                raise SessionLoginRequired(site) from None
            raise SessionNotReady(site) from None
        except (SealError, RunnerFailure, ValueError):
            raise SessionNotReady(site) from None
