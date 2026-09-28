"""Runner side of the session broker: ready revisions and one-task Cookie leases."""

from __future__ import annotations

import json
import secrets
import time

import httpx
from app.integrations.site_session_catalog import site_target
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.netscape_cookie import serialize_cookies
from app.workers.runner.provider_session_files import validated_cookie_payload
from app.workers.runner.provider_session_headers import yuanbao_session_cookie_jar
from app.workers.session.contracts import (
    FAILURE_PATH,
    LEASE_PATH,
    STATUS_PATH,
    FailureReport,
    LeaseRequest,
    LeaseResponse,
    StatusRequest,
    StatusResponse,
    lease_associated_data,
)
from app.workers.session.rpc import RpcError, SignedClient
from app.workers.session.sealing import (
    SealError,
    decode,
    encode,
    open_sealed,
    public_key,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

_TIMEOUT_SECONDS = 20


def context_version(site: str, seed_revision: int) -> str:
    return f"{site}:{seed_revision}"


def parse_context_version(value: str | None) -> tuple[str, int]:
    site, _, revision = (value or "").rpartition(":")
    if not site or not revision.isdigit() or int(revision) < 1:
        raise RunnerFailure("credential_revoked", status=422)
    return site, int(revision)


class SiteSessionClient:
    def __init__(self, base_url: str, secret: bytes) -> None:
        self._http = httpx.AsyncClient(base_url=base_url, timeout=_TIMEOUT_SECONDS)
        self._client = SignedClient(self._http, secret)

    async def ready_revision(self, site: str) -> int:
        try:
            response = await self._client.post(
                STATUS_PATH, StatusRequest(site=site), StatusResponse
            )
        except RpcError as exc:
            raise _failure(exc) from exc
        return response.seed_revision

    async def lease(self, site: str, seed_revision: int) -> bytes:
        """Return a validated Netscape payload for one operation only."""
        key = X25519PrivateKey.generate()
        task_id = secrets.token_urlsafe(16)
        try:
            grant = await self._client.post(
                LEASE_PATH,
                LeaseRequest(
                    task_id=task_id,
                    site=site,
                    seed_revision=seed_revision,
                    public_key=encode(public_key(key)),
                ),
                LeaseResponse,
            )
        except RpcError as exc:
            raise _failure(exc) from exc
        if grant.expires_at <= time.time():
            raise RunnerFailure("provider_session_not_ready", status=503)

        def opened(kind: str, value: str) -> bytes:
            return open_sealed(
                decode(value),
                key,
                associated_data=lease_associated_data(
                    kind, task_id, site, seed_revision, grant.expires_at
                ),
            )

        try:
            jar = opened("jar", grant.jar)
            headers = (
                None if grant.headers is None else opened("headers", grant.headers)
            )
        except SealError as exc:
            raise RunnerFailure("provider_session_not_ready", status=503) from exc
        target = site_target(site)
        payload = validated_cookie_payload(jar, target.cookie_domains)
        if headers is None:
            return payload
        # WeChat Channels: page identity and request headers travel as private
        # Cookie entries the extractor already understands.
        try:
            auth = json.loads(headers)
        except ValueError:
            auth = None
        if not isinstance(auth, dict):
            raise RunnerFailure("provider_session_not_ready", status=503)
        extra = serialize_cookies(yuanbao_session_cookie_jar(auth))
        return payload + extra.split(b"\n", 1)[1]

    async def report(self, site: str, seed_revision: int, error_code: str) -> None:
        """Best effort: a lost report only delays the broker's own keepalive."""
        try:
            await self._client.post_empty(
                FAILURE_PATH,
                FailureReport(
                    site=site, seed_revision=seed_revision, error_code=error_code
                ),
            )
        except (RpcError, ValueError):
            pass

    async def close(self) -> None:
        await self._http.aclose()


def _failure(error: RpcError) -> RunnerFailure:
    if error.code == "provider_session_not_ready":
        return RunnerFailure("provider_session_not_ready", status=503)
    return RunnerFailure("provider_session_unavailable", status=503)
