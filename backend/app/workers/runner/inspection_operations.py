"""Bounded receipts for current inspection resources, never a task scheduler."""

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.workers.runner.contracts import (
    InspectionOperationResponse,
    InspectResponse,
    ProviderFailureContract,
)
from app.workers.runner.errors import RunnerFailure


@dataclass(slots=True)
class _Operation:
    task: asyncio.Task[object] | None
    fingerprint: str
    receipt: InspectionOperationResponse


class InspectionOperationRegistry:
    def __init__(self, max_active: int, *, max_receipts: int = 128) -> None:
        self._max_active = max_active
        self._max_receipts = max(max_active, max_receipts)
        self._operations: OrderedDict[str, _Operation] = OrderedDict()

    async def run(
        self,
        operation_id: str,
        fingerprint: str,
        execute: Callable[[], Awaitable[InspectResponse]],
    ) -> InspectResponse:
        previous = self._operations.get(operation_id)
        if previous is not None:
            if previous.fingerprint != fingerprint:
                raise RunnerFailure("context_changed", status=409)
            raise RunnerFailure("outcome_unknown", status=409)
        if (
            sum(item.task is not None for item in self._operations.values())
            >= self._max_active
        ):
            raise RunnerFailure("runner_busy", status=503)
        while len(self._operations) >= self._max_receipts:
            completed = next(
                (key for key, item in self._operations.items() if item.task is None),
                None,
            )
            if completed is None:
                raise RunnerFailure("runner_busy", status=503)
            self._operations.pop(completed)
        task = asyncio.current_task()
        if task is None:
            raise RunnerFailure("internal_error", status=500)
        operation = _Operation(
            task, fingerprint, InspectionOperationResponse(status="active")
        )
        self._operations[operation_id] = operation
        try:
            result = await execute()
            operation.receipt = InspectionOperationResponse(
                status="succeeded", result=result
            )
            return result
        except RunnerFailure as error:
            operation.receipt = InspectionOperationResponse(
                status="failed",
                failure=ProviderFailureContract.from_domain(error.failure),
            )
            raise
        except asyncio.CancelledError:
            operation.receipt = InspectionOperationResponse(
                status="cancelled",
                failure=ProviderFailureContract.from_domain(
                    RunnerFailure("cancelled", status=409).failure
                ),
            )
            raise
        except Exception:
            operation.receipt = InspectionOperationResponse(status="outcome_unknown")
            raise
        finally:
            # execute() has awaited child-process and session cleanup here.
            operation.task = None

    def status(self, operation_id: str) -> InspectionOperationResponse:
        operation = self._operations.get(operation_id)
        if operation is None:
            return InspectionOperationResponse(status="outcome_unknown")
        return operation.receipt

    async def cancel(self, operation_id: str) -> InspectionOperationResponse:
        operation = self._operations.get(operation_id)
        if operation is None:
            return InspectionOperationResponse(status="outcome_unknown")
        task = operation.task
        if task is not None and not task.done():
            task.cancel()
            try:
                async with asyncio.timeout(20):
                    await asyncio.shield(asyncio.gather(task, return_exceptions=True))
            except TimeoutError:
                return InspectionOperationResponse(status="active")
        return operation.receipt
