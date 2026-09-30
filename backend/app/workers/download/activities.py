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
from app.services.downloads.resolution import ResolutionExecution, ResolutionPlan
from app.services.provider_failures import (
    FailureEvidenceKind,
    FailurePhase,
    ProviderFailure,
)
from app.workers.download.workflows import (
    InspectionCommand,
    InspectionOutcome,
    InspectionWait,
)
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
        operation_id = (
            f"prepare:{command.intent_id}:{command.generation}:{info.activity_id}"
        )
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
        operation = await self._repository.claim_preparation(
            intent_id, command.generation, operation_id, now=self._clock()
        )
        if operation is None:
            return outcome(await self._repository.execution_state(intent_id))
        if not operation.newly_claimed:
            return await self._reconcile(command)
        snapshot = operation.intent
        execution = operation.execution
        try:
            try:
                url = self._cipher.decrypt(operation.url)
            except Exception:
                raise ApplicationError(ApplicationErrorCode.INTERNAL_ERROR) from None
            if not self._inspector.is_import_only(url):
                async with asyncio.timeout(
                    max(0, min(60, (snapshot.deadline - self._clock()).total_seconds()))
                ):
                    plan = snapshot.resolution_plan
                    if plan is None:
                        capability = await self._inspector.resolution_capability(
                            url, snapshot.access_policy
                        )
                        plan = ResolutionPlan(capability, snapshot.generation)
                        snapshot = await self._repository.bind_plan(
                            snapshot, plan, now=self._clock()
                        )
                    assert snapshot.next_strategy_id is not None
                    preparation = await self._inspector.prepare_resolution(
                        url, plan, snapshot.next_strategy_id
                    )
                operation = await self._repository.begin_attempt(
                    snapshot, preparation, now=self._clock()
                )
                if operation is None:
                    return outcome(await self._repository.execution_state(intent_id))
                snapshot = operation.intent
                execution = operation.execution
            remaining = snapshot.remaining_budget_ms / 1000
            if operation.execution is not None:
                remaining = min(
                    remaining,
                    (operation.execution.deadline_at - self._clock()).total_seconds(),
                )
            async with asyncio.timeout(max(0, remaining)):
                result = await self._inspector.prepare(
                    url,
                    snapshot.owner_hash,
                    f"intent:{snapshot.id}:{snapshot.fence}",
                    access_policy=snapshot.access_policy,
                    execution=operation.execution,
                )
            return outcome(
                await self._repository.complete(snapshot, result, now=self._clock())
            )
        except asyncio.CancelledError:
            if execution is not None:
                await self._cancel_and_wait(snapshot, execution)
            raise
        except (ApplicationError, TimeoutError) as exc:
            if isinstance(exc, TimeoutError) and execution is not None:
                return await self._reconcile(command)
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
                        failure=(
                            exc.failure
                            if isinstance(exc, ApplicationError)
                            else ProviderFailure.for_code(
                                "inspection_timeout",
                                phase=FailurePhase.PREPARE_CONTEXT,
                                evidence_kind=FailureEvidenceKind.TRANSPORT,
                            )
                        ),
                    )
                )
            except PersistenceConflict:
                return outcome(await self._repository.execution_state(intent_id))
        except PersistenceConflict:
            return outcome(await self._repository.execution_state(intent_id))

    async def _stop_operation(
        self, snapshot: IntentSnapshot, execution: ResolutionExecution
    ) -> None:
        if await self._inspector.cancel_resolution(execution):
            await self._repository.abandon_attempt(snapshot, now=self._clock())

    async def _cancel_and_wait(
        self, snapshot: IntentSnapshot, execution: ResolutionExecution
    ) -> None:
        cleanup = asyncio.create_task(self._stop_operation(snapshot, execution))
        try:
            async with asyncio.timeout(30):
                await asyncio.shield(cleanup)
        except Exception:
            # No ACK means unknown ownership; never authorize replacement.
            cleanup.cancel()
            await asyncio.gather(cleanup, return_exceptions=True)

    async def _reconcile(self, command: InspectionCommand) -> InspectionOutcome:
        intent_id = UUID(command.intent_id)
        operation = await self._repository.running_operation(
            intent_id, command.generation
        )
        if operation is None or operation.execution is None:
            return outcome(
                await self._repository.fail_generation(
                    intent_id, command.generation, now=self._clock()
                )
            )
        snapshot = operation.intent
        try:
            result = await self._inspector.prepare(
                self._cipher.decrypt(operation.url),
                snapshot.owner_hash,
                f"intent:{snapshot.id}:{snapshot.fence}",
                access_policy=snapshot.access_policy,
                execution=operation.execution,
                reconcile_only=True,
            )
            return outcome(
                await self._repository.complete(snapshot, result, now=self._clock())
            )
        except asyncio.CancelledError:
            await self._cancel_and_wait(snapshot, operation.execution)
            raise
        except ApplicationError as exc:
            return outcome(
                await self._repository.fail(
                    snapshot,
                    now=self._clock(),
                    reason_code=exc.code.value,
                    retry_at=exc.retry_at,
                    failure=exc.failure,
                )
            )
        except PersistenceConflict:
            return outcome(await self._repository.execution_state(intent_id))

    @activity.defn(name="expire_inspection_wait")
    async def expire_inspection_wait(
        self, command: InspectionWait
    ) -> InspectionOutcome:
        try:
            return outcome(
                await self._repository.expire_wait(
                    UUID(command.intent_id),
                    command.generation,
                    UUID(command.authorization_id),
                    now=self._clock(),
                )
            )
        except Exception:
            raise TemporalApplicationError(
                "inspection wait reconciliation unavailable",
                type="InspectionInfrastructure",
            ) from None

    @activity.defn(name="finish_inspection")
    async def finish_inspection(self, command: InspectionCommand) -> InspectionOutcome:
        try:
            return await self._reconcile(command)
        except Exception:
            raise TemporalApplicationError(
                "inspection reconciliation unavailable", type="InspectionInfrastructure"
            ) from None


def outcome(snapshot: IntentSnapshot) -> InspectionOutcome:
    return InspectionOutcome(
        snapshot.status.value,
        str(snapshot.inspection_id) if snapshot.inspection_id else None,
        snapshot.retry_at.timestamp() if snapshot.retry_at else None,
        str(snapshot.authorization_id) if snapshot.authorization_id else None,
        snapshot.authorization_deadline.timestamp()
        if snapshot.authorization_deadline
        else None,
    )
