"""Cancel Outbox delivery requires both scheduling and Runner confirmations."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.integrations.messaging import EventEnvelope
from app.integrations.temporal_client import CommandPublisher
from app.services.downloads.intent_models import IntentSnapshot, IntentStatus
from app.workers.download.workflows import InspectionCommand
from temporalio.service import RPCError, RPCStatusCode

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def setup():
    state = IntentSnapshot(
        uuid4(),
        "a" * 64,
        IntentStatus.CANCELLING,
        2,
        NOW + timedelta(seconds=120),
        0,
        None,
        None,
        "cancelled",
        NOW,
        NOW,
    )
    repo = AsyncMock()
    repo.execution_state.return_value = state
    handle = AsyncMock()
    client = AsyncMock()
    client.get_workflow_handle = lambda _: handle
    stopped = AsyncMock()
    publisher = CommandPublisher(
        AsyncMock(),
        repo,
        AsyncMock(),
        address="localhost:7233",
        namespace="test",
        cancel_inspection=stopped,
        clock=lambda: NOW,
    )
    publisher._client = client
    event = EventEnvelope(
        schema_version=1,
        event_id=uuid4(),
        aggregate_id=state.id,
        event_type="download.intent.cancelled",
        occurred_at=NOW,
        payload={"intent_id": str(state.id), "generation": 0},
    )
    return publisher, repo, handle, stopped, event


async def test_cancel_waits_for_workflow_stop_before_runner_cleanup():
    publisher, repo, handle, stopped, event = setup()
    wait_started, workflow_closed = asyncio.Event(), asyncio.Event()

    async def result(**kwargs):
        wait_started.set()
        await workflow_closed.wait()

    handle.result.side_effect = result
    task = asyncio.create_task(publisher.publish(event))
    await wait_started.wait()
    stopped.assert_not_awaited()
    repo.confirm_cancel.assert_not_awaited()
    workflow_closed.set()
    await task
    stopped.assert_awaited_once_with(
        InspectionCommand(str(event.aggregate_id), 0).task_id
    )
    repo.confirm_cancel.assert_awaited_once_with(event.aggregate_id, 0, now=NOW)


async def test_lost_runner_cancel_ack_is_retried_before_terminal_commit():
    publisher, repo, handle, stopped, event = setup()
    stopped.side_effect = [RuntimeError("response lost"), None]
    with pytest.raises(RuntimeError, match="response lost"):
        await publisher.publish(event)
    repo.confirm_cancel.assert_not_awaited()
    await publisher.publish(event)
    assert stopped.await_count == 2
    repo.confirm_cancel.assert_awaited_once()


async def test_missing_workflow_still_requires_runner_cleanup_confirmation():
    publisher, repo, handle, stopped, event = setup()
    handle.cancel.side_effect = RPCError("not found", RPCStatusCode.NOT_FOUND, b"")
    await publisher.publish(event)
    handle.result.assert_not_awaited()
    stopped.assert_awaited_once()
    repo.confirm_cancel.assert_awaited_once()


async def test_failed_temporal_cancel_never_confirms_the_intent():
    publisher, repo, handle, stopped, event = setup()
    handle.cancel.side_effect = RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b"")
    with pytest.raises(RPCError):
        await publisher.publish(event)
    stopped.assert_not_awaited()
    repo.confirm_cancel.assert_not_awaited()


async def test_completed_cancel_redelivery_never_reopens_workflow():
    publisher, repo, handle, stopped, event = setup()
    repo.execution_state.return_value = replace(
        repo.execution_state.return_value, status=IntentStatus.CANCELLED
    )
    await publisher.publish(event)
    handle.cancel.assert_not_awaited()
    stopped.assert_not_awaited()
