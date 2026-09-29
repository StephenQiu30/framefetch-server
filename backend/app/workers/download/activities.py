"""Inspection I/O and atomic result publication, outside Workflow replay."""

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from app.repositories.downloads.intent_repository import IntentRepository
from app.services.downloads.errors import (
    ApplicationError,
    ApplicationErrorCode,
    PersistenceConflict,
)
from app.services.downloads.inspect_media import InspectMedia
from app.services.downloads.intent_models import IntentSnapshot
from app.services.downloads.ports import UrlCipher
from app.workers.download.workflows import InspectionCommand, InspectionOutcome
from temporalio import activity
from temporalio.exceptions import ApplicationError as TemporalApplicationError

_RETRYABLE = {
    ApplicationErrorCode.INSPECTION_TIMEOUT,
    ApplicationErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE,
    ApplicationErrorCode.PROVIDER_RATE_LIMITED,
    ApplicationErrorCode.PROVIDER_SESSION_NOT_READY,
}


class InspectionActivities:
    def __init__(
        self,
        repository: IntentRepository,
        inspector: InspectMedia,
        cipher: UrlCipher,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._inspector = inspector
        self._cipher = cipher
        self._clock = clock

    @activity.defn(name="inspect_media")
    async def inspect_media(self, command: InspectionCommand) -> InspectionOutcome:
        info = activity.info()
        operation_id = f"{info.workflow_run_id}:{info.activity_id}:{info.attempt}"
        heartbeat = asyncio.create_task(self._heartbeat())
        try:
            return await self.execute(command, operation_id)
        except asyncio.CancelledError:
            # Cancelling InspectMedia propagates through RPC to Runner cleanup.
            raise
        except Exception:
            # SDK failure serialization must never contain DB URLs or source URLs.
            raise TemporalApplicationError(
                "inspection infrastructure unavailable", type="InspectionInfrastructure"
            ) from None
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _heartbeat(self) -> None:
        while True:
            activity.heartbeat()
            await asyncio.sleep(5)

    async def execute(
        self, command: InspectionCommand, operation_id: str
    ) -> InspectionOutcome:
        intent_id = UUID(command.intent_id)
        operation = await self._repository.begin_attempt(
            intent_id, command.generation, operation_id, now=self._clock()
        )
        if operation is None:
            return outcome(await self._repository.execution_state(intent_id))
        snapshot = operation.intent
        remaining = min(
            snapshot.remaining_budget_ms / 1000,
            (snapshot.deadline - self._clock()).total_seconds(),
        )
        try:
            try:
                url = self._cipher.decrypt(operation.url)
            except Exception:
                raise ApplicationError(ApplicationErrorCode.INTERNAL_ERROR) from None
            async with asyncio.timeout(max(0, remaining)):
                result = await self._inspector.prepare(
                    url,
                    snapshot.owner_hash,
                    f"intent:{snapshot.id}:{snapshot.fence}",
                    access_policy=snapshot.access_policy,
                )
            return outcome(
                await self._repository.complete(snapshot, result, now=self._clock())
            )
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
                    else min(30, 2**snapshot.attempt)
                )
                retry_at = now + timedelta(seconds=delay)
                if isinstance(exc, ApplicationError) and exc.retry_at is not None:
                    retry_at = max(retry_at, exc.retry_at)
            try:
                return outcome(
                    await self._repository.fail(
                        snapshot,
                        now=now,
                        reason_code=code.value,
                        retry_at=retry_at,
                        preparation_wait=isinstance(exc, ApplicationError)
                        and exc.preparation_wait
                        and code is ApplicationErrorCode.PROVIDER_SESSION_NOT_READY,
                    )
                )
            except PersistenceConflict:
                return outcome(await self._repository.execution_state(intent_id))
        except PersistenceConflict:
            return outcome(await self._repository.execution_state(intent_id))

    @activity.defn(name="finish_inspection")
    async def finish_inspection(self, command: InspectionCommand) -> InspectionOutcome:
        try:
            return outcome(
                await self._repository.fail_generation(
                    UUID(command.intent_id), command.generation, now=self._clock()
                )
            )
        except Exception:
            raise TemporalApplicationError(
                "inspection reconciliation unavailable", type="InspectionInfrastructure"
            ) from None


def outcome(snapshot: IntentSnapshot) -> InspectionOutcome:
    return InspectionOutcome(
        snapshot.status.value,
        str(snapshot.inspection_id) if snapshot.inspection_id else None,
        snapshot.retry_at.timestamp() if snapshot.retry_at else None,
    )
