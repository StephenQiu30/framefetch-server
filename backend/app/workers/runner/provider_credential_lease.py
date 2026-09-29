"""Serialize operator credential use inside the single session Runner.

One Runner process serves every operator-session operation, so an in-process
lock per credential identity is sufficient; no external lease store is needed.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.workers.runner.errors import RunnerFailure


class ProviderCredentialLocks:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def hold(
        self,
        provider: str,
        credential_version: str,
        *,
        wait_seconds: float = 0,
    ) -> AsyncIterator[None]:
        """Hold one credential; ``wait_seconds`` queues behind the current holder."""
        lock = self._locks.setdefault(
            lock_key(provider, credential_version), asyncio.Lock()
        )
        if wait_seconds <= 0:
            if lock.locked():
                raise RunnerFailure("provider_session_unavailable", status=503)
            await lock.acquire()
        else:
            try:
                await asyncio.wait_for(lock.acquire(), wait_seconds)
            except TimeoutError:
                raise RunnerFailure(
                    "provider_session_unavailable", status=503
                ) from None
        try:
            yield
        finally:
            lock.release()


def lock_key(provider: str, credential_version: str) -> str:
    """Return the lock identity for a non-secret credential version."""
    return f"{provider}:{credential_version}"
