"""Resolve I/O and atomic result publication, outside Workflow replay."""

import asyncio
from collections.abc import Callable
from datetime import datetime
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
from app.services.provider_failures import ProviderFailure
from app.workers.download.workflows import InspectionCommand, InspectionOutcome
from temporalio import activity
from temporalio.exceptions import ApplicationError as TemporalApplicationError


class InspectionActivities:
    def __init__(
        self,
        repository: IntentRepository,
        inspector: InspectMedia,
        cipher: UrlCipher,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository, self._inspector, self._cipher = repository, inspector, cipher
        self._clock = clock

    @activity.defn(name="resolve")
    async def resolve(self, command: InspectionCommand) -> InspectionOutcome:
        heartbeat = asyncio.create_task(self._heartbeat())
        try:
            return await self.execute(command, recover=activity.info().attempt > 1)
        except asyncio.CancelledError:
            raise
        except Exception:
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
        self, command: InspectionCommand, *, recover: bool = False
    ) -> InspectionOutcome:
        intent_id = UUID(command.intent_id)
        operation = await self._repository.claim(
            intent_id, command.generation, now=self._clock(), recover=recover
        )
        if operation is None:
            return outcome(await self._repository.execution_state(intent_id))
        snapshot = operation.intent
        try:
            # A Worker-only restart can leave the previous read-only call alive.
            # Its resources must be confirmed stopped before the same ID is reused.
            await self._inspector.cancel(command.task_id)
            state = await self._repository.execution_state(intent_id)
            if state.version != snapshot.version or state.status != snapshot.status:
                return outcome(state)
            try:
                url = self._cipher.decrypt(operation.url)
            except Exception:
                raise ApplicationError(
                    ApplicationErrorCode.RUNTIME_UNAVAILABLE
                ) from None
            remaining = max(
                0, min(120, (snapshot.deadline - self._clock()).total_seconds())
            )
            if remaining <= 0:
                raise TimeoutError("inspection deadline reached")
            async with asyncio.timeout(remaining):
                result = await self._inspector.prepare(
                    url,
                    snapshot.owner_hash,
                    f"intent:{snapshot.id}:{snapshot.generation}",
                    task_id=command.task_id,
                    deadline=snapshot.deadline,
                )
            return outcome(
                await self._repository.complete(snapshot, result, now=self._clock())
            )
        except asyncio.CancelledError:
            # The bound Runner must acknowledge cleanup before a terminal update.
            # Worker shutdown without an API cancel stays recoverable.
            await self._inspector.cancel(command.task_id)
            await self._repository.confirm_cancel(
                intent_id, command.generation, now=self._clock()
            )
            raise
        except (ApplicationError, TimeoutError) as exc:
            await self._inspector.cancel(command.task_id)
            code = (
                exc.code
                if isinstance(exc, ApplicationError)
                else ApplicationErrorCode.TRANSIENT
            )
            failure = (
                exc.failure if isinstance(exc, ApplicationError) else None
            ) or ProviderFailure.for_code(code.value)
            try:
                return outcome(
                    await self._repository.fail(
                        snapshot,
                        now=self._clock(),
                        reason_code=code.value,
                        failure=failure,
                    )
                )
            except PersistenceConflict:
                return outcome(await self._repository.execution_state(intent_id))
        except PersistenceConflict:
            return outcome(await self._repository.execution_state(intent_id))
        # Infrastructure errors escape into Temporal retry. The next attempt
        # claims a new business version and preserves the original deadline.


def outcome(snapshot: IntentSnapshot) -> InspectionOutcome:
    return InspectionOutcome(
        snapshot.status.value,
        str(snapshot.inspection_id) if snapshot.inspection_id else None,
    )
