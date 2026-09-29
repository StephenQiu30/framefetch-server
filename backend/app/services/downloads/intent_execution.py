"""Leased parse execution; all retries and deadlines belong to the intent."""

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timedelta
from uuid import UUID

from app.services.download_execution.models import ExecutionDisposition
from app.services.downloads.errors import (
    ApplicationError,
    ApplicationErrorCode,
    PersistenceConflict,
)
from app.services.downloads.inspect_media import InspectMedia
from app.services.downloads.intent_models import IntentSnapshot
from app.services.downloads.intents import IntentPersistence
from app.services.downloads.ports import UrlCipher

_RETRYABLE = {
    ApplicationErrorCode.INSPECTION_TIMEOUT,
    ApplicationErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE,
    ApplicationErrorCode.PROVIDER_RATE_LIMITED,
    ApplicationErrorCode.PROVIDER_SESSION_NOT_READY,
}


class IntentExecution:
    def __init__(
        self,
        repository: IntentPersistence,
        inspector: InspectMedia,
        cipher: UrlCipher,
        *,
        worker_id: str,
        clock: Callable[[], datetime],
        heartbeat_interval: float = 2,
        lease_for: timedelta = timedelta(seconds=15),
    ) -> None:
        if (
            not worker_id
            or heartbeat_interval <= 0
            or lease_for.total_seconds() <= heartbeat_interval * 2
        ):
            raise ValueError("invalid intent execution lease settings")
        self._repository = repository
        self._inspector = inspector
        self._cipher = cipher
        self._worker_id = worker_id
        self._clock = clock
        self._heartbeat_interval = heartbeat_interval
        self._lease_for = lease_for

    async def execute(self, intent_id: UUID) -> ExecutionDisposition:
        lease = await self._repository.claim(
            intent_id, self._worker_id, now=self._clock(), lease_for=self._lease_for
        )
        if lease is None:
            return ExecutionDisposition.ACK
        try:
            url = self._cipher.decrypt(lease.url)
        except Exception:
            with suppress(PersistenceConflict):
                await self._repository.fail(
                    lease.intent,
                    now=self._clock(),
                    reason_code=ApplicationErrorCode.INTERNAL_ERROR.value,
                )
            return ExecutionDisposition.ACK
        remaining = min(
            lease.intent.remaining_budget_ms / 1000,
            (lease.intent.deadline - self._clock()).total_seconds(),
        )
        heartbeat = asyncio.create_task(self._heartbeat(lease.intent))
        work = asyncio.create_task(self._resolve(lease.intent, url, max(0, remaining)))
        try:
            done, _ = await asyncio.wait(
                {work, heartbeat}, return_when=asyncio.FIRST_COMPLETED
            )
            if heartbeat in done:
                # Cancellation, expiry or storage loss stops the operation before
                # any more results can commit; the database remains authoritative.
                heartbeat.result()
                return ExecutionDisposition.ACK
            work.result()
            return ExecutionDisposition.ACK
        finally:
            for task in (work, heartbeat):
                task.cancel()
            await asyncio.gather(work, heartbeat, return_exceptions=True)

    async def _heartbeat(self, lease: IntentSnapshot) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_interval)
            if not await self._repository.heartbeat(
                lease, now=self._clock(), lease_for=self._lease_for
            ):
                return

    async def _resolve(self, lease: IntentSnapshot, url: str, remaining: float) -> None:
        try:
            async with asyncio.timeout(remaining):
                result = await self._inspector.prepare(
                    url,
                    lease.owner_hash,
                    f"intent:{lease.id}:{lease.fence}",
                    access_policy=lease.access_policy,
                )
            await self._repository.complete(lease, result, now=self._clock())
        except PersistenceConflict:
            return
        except (ApplicationError, TimeoutError) as exc:
            now = self._clock()
            code = (
                exc.code
                if isinstance(exc, ApplicationError)
                else ApplicationErrorCode.INSPECTION_TIMEOUT
            )
            retry_at = None
            if code in _RETRYABLE:
                delay = (
                    15
                    if code is ApplicationErrorCode.PROVIDER_SESSION_NOT_READY
                    else min(30, 2**lease.attempt)
                )
                retry_at = now + timedelta(seconds=delay)
                if isinstance(exc, ApplicationError) and exc.retry_at is not None:
                    retry_at = max(retry_at, exc.retry_at)
            with suppress(PersistenceConflict):
                await self._repository.fail(
                    lease,
                    now=now,
                    reason_code=code.value,
                    retry_at=retry_at,
                    preparation_wait=(
                        isinstance(exc, ApplicationError)
                        and exc.preparation_wait
                        and code is ApplicationErrorCode.PROVIDER_SESSION_NOT_READY
                    ),
                )
