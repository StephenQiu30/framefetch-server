"""Redis-backed leases for serialized operator credential use."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.workers.runner.errors import RunnerFailure
from redis.asyncio import Redis

_KEY_PREFIX = "video:provider-credential-lease:"
_POLL_SECONDS = 0.25

_RENEW_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class ProviderCredentialLeaseCoordinator:
    """Coordinate one credential version across all operator runner replicas."""

    def __init__(
        self,
        url: str,
        *,
        ttl_seconds: int = 120,
        heartbeat_seconds: float = 30,
    ) -> None:
        if not url:
            raise ValueError("provider credential lease URL is required")
        if ttl_seconds <= 0 or heartbeat_seconds <= 0:
            raise ValueError("provider credential lease timings must be positive")
        if heartbeat_seconds >= ttl_seconds:
            raise ValueError("provider credential lease heartbeat must be below TTL")
        self._client: Any = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        self._ttl_ms = ttl_seconds * 1000
        self._heartbeat_seconds = heartbeat_seconds

    @asynccontextmanager
    async def hold(
        self,
        provider: str,
        credential_version: str,
        *,
        wait_seconds: float = 0,
    ) -> AsyncIterator[None]:
        """Hold one credential; ``wait_seconds`` queues behind the current holder.

        Maintenance passes 0 and skips a busy site; request paths wait so a
        keepalive or a sibling operation is not reported as a failure.
        """
        key = lease_key(provider, credential_version)
        token = secrets.token_urlsafe(32)
        deadline = time.monotonic() + max(0.0, wait_seconds)
        while True:
            try:
                acquired = await self._client.set(
                    key,
                    token,
                    nx=True,
                    px=self._ttl_ms,
                )
            except Exception as exc:
                raise RunnerFailure("provider_session_unavailable", status=503) from exc
            if acquired:
                break
            if time.monotonic() >= deadline:
                raise RunnerFailure("provider_session_unavailable", status=503)
            await asyncio.sleep(_POLL_SECONDS)

        owner = asyncio.current_task()
        heartbeat = asyncio.create_task(self._heartbeat(key, token, owner))
        try:
            yield
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
            await self._release(key, token)

    async def ping(self) -> None:
        try:
            await self._client.ping()
        except Exception as exc:
            raise RunnerFailure("provider_session_unavailable", status=503) from exc

    async def close(self) -> None:
        await self._client.aclose()

    async def _heartbeat(
        self,
        key: str,
        token: str,
        owner: asyncio.Task[Any] | None,
    ) -> None:
        try:
            while True:
                await asyncio.sleep(self._heartbeat_seconds)
                try:
                    renewed = await self._client.eval(
                        _RENEW_SCRIPT,
                        1,
                        key,
                        token,
                        str(self._ttl_ms),
                    )
                except Exception:
                    renewed = 0
                if int(renewed) != 1:
                    if owner is not None:
                        owner.cancel()
                    return
        except asyncio.CancelledError:
            raise

    async def _release(self, key: str, token: str) -> None:
        try:
            await self._client.eval(_RELEASE_SCRIPT, 1, key, token)
        except Exception:
            # The TTL remains the last line of defence if Redis is unavailable
            # during cleanup. Never delete a value owned by another runner.
            return


def lease_key(provider: str, credential_version: str) -> str:
    """Return the namespaced Redis key for a non-secret credential identity."""
    return f"{_KEY_PREFIX}{provider}:{credential_version}"
