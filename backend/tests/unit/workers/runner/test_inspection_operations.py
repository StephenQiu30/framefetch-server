"""Receipts reconcile one submitted operation; they never schedule replacements."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.inspection_operations import InspectionOperationRegistry
from tests.unit.workers.runner.api_helpers import FakeService


async def test_completed_receipt_is_queryable_without_reexecuting_or_accepting_drift():
    registry = InspectionOperationRegistry(1)
    result = await FakeService().inspect("https://media.example/owned")
    execute = AsyncMock(return_value=result)
    assert await registry.run("a" * 64, "frozen", execute) == result
    assert registry.status("a" * 64).result == result
    with pytest.raises(RunnerFailure) as duplicate:
        await registry.run("a" * 64, "frozen", execute)
    assert duplicate.value.code == "outcome_unknown"
    with pytest.raises(RunnerFailure) as drift:
        await registry.run("a" * 64, "changed", execute)
    assert drift.value.code == "context_changed"
    execute.assert_awaited_once()
    assert registry.status("b" * 64).status == "outcome_unknown"
    assert (await registry.cancel("b" * 64)).status == "outcome_unknown"


async def test_active_call_cannot_be_replaced_and_cancel_ack_waits_for_cleanup():
    registry = InspectionOperationRegistry(1, max_receipts=1)
    entered, cancelling, cleaned = (asyncio.Event() for _ in range(3))

    async def execute():
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cancelling.set()
            await cleaned.wait()

    task = asyncio.create_task(registry.run("a" * 64, "frozen", execute))
    await entered.wait()
    other = AsyncMock()
    with pytest.raises(RunnerFailure) as duplicate:
        await registry.run("a" * 64, "frozen", other)
    assert duplicate.value.code == "outcome_unknown"
    with pytest.raises(RunnerFailure) as busy:
        await registry.run("b" * 64, "other", other)
    assert busy.value.code == "runner_busy"
    cancellation = asyncio.create_task(registry.cancel("a" * 64))
    await cancelling.wait()
    assert registry.status("a" * 64).status == "active"
    assert not cancellation.done()  # A business cancel alone is no cleanup proof.
    cleaned.set()
    assert (await cancellation).status == "cancelled"
    with pytest.raises(asyncio.CancelledError):
        await task
    other.assert_not_awaited()


async def test_only_completed_receipts_are_evicted_and_missing_history_is_unknown():
    registry = InspectionOperationRegistry(1, max_receipts=1)
    result = await FakeService().inspect("https://media.example/owned")
    for identity in ("a", "b"):
        await registry.run(identity * 64, identity, AsyncMock(return_value=result))
    assert registry.status("a" * 64).status == "outcome_unknown"
    assert registry.status("b" * 64).status == "succeeded"


async def test_failed_receipt_retains_original_fact_and_unexpected_errors_are_unknown():
    registry = InspectionOperationRegistry(1)
    error = RunnerFailure("pot_rejected", status=422)
    with pytest.raises(RunnerFailure):
        await registry.run("a" * 64, "frozen", AsyncMock(side_effect=error))
    receipt = registry.status("a" * 64)
    assert receipt.status == "failed" and receipt.failure.to_domain() == error.failure
    with pytest.raises(RuntimeError):
        await registry.run("b" * 64, "other", AsyncMock(side_effect=RuntimeError()))
    assert registry.status("b" * 64).status == "outcome_unknown"
