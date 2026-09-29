"""Real Temporal transport, with an isolated CLI test server as the CI default."""

import asyncio
import os
import shutil
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from app.integrations.temporal_client import CommandPublisher
from app.models import MediaInspectionRow, OutboxEventRow
from app.repositories.outbox_repository import SqlAlchemyOutboxRepository
from app.workers.download.workflows import InspectionCommand, InspectionWorkflow
from app.workers.outbox.loop import OutboxPublisherLoop
from sqlalchemy import func, select
from temporalio.api.workflowservice.v1 import RegisterNamespaceRequest
from temporalio.client import Client, WorkflowFailureError
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker
from tests.integration.api.test_download_intent_routes import (
    URL,
    WaitingRunner,
    components,
)
from tests.integration.api.test_download_routes import TEST_USER
from tests.unit.services.fakes import FakeRunner
from tests.unit.services.test_inspect_media import runner_result


@pytest.fixture
async def temporal_client():
    address = os.environ.get("TEST_TEMPORAL_ADDRESS")
    if not address:
        async with await WorkflowEnvironment.start_local(
            namespace="framefetch-test",
            dev_server_existing_path=shutil.which("temporal"),
            dev_server_download_version="v1.8.2",
        ) as environment:
            yield environment.client
        return
    client = await Client.connect(address, namespace="framefetch-test")
    request = RegisterNamespaceRequest(namespace="framefetch-test")
    request.workflow_execution_retention_period.FromTimedelta(timedelta(days=1))
    try:
        await client.workflow_service.register_namespace(request)
    except RPCError as exc:
        if exc.status != RPCStatusCode.ALREADY_EXISTS:
            raise
    yield client


def worker(client, activities):
    return Worker(
        client,
        task_queue="ff-inspect",
        workflows=[InspectionWorkflow],
        activities=[activities.inspect_media, activities.finish_inspection],
        max_concurrent_activities=2,
        graceful_shutdown_timeout=timedelta(seconds=1),
        max_heartbeat_throttle_interval=timedelta(milliseconds=100),
    )


def dispatch(repo, sessions, clock, client):
    publisher = CommandPublisher(
        AsyncMock(),
        repo,
        address=client.service_client.config.target_host,
        namespace="framefetch-test",
    )
    return OutboxPublisherLoop(
        repository=SqlAlchemyOutboxRepository(sessions),
        publisher=publisher,
        publisher_id="test-publisher",
        clock=lambda: clock[0],
    )


async def test_start_ack_loss_worker_restart_replay_and_one_result(
    postgres_engine,
    temporal_client,
):
    runner = WaitingRunner()
    service, repo, activities, clock, sessions = components(postgres_engine, runner)
    intent = await service.create(URL, TEST_USER.owner_hash, "outbox")
    command = InspectionCommand(str(intent.id), 0)
    loop = dispatch(repo, sessions, clock, temporal_client)
    # Acceptance and delivery survive an offline worker.
    assert await loop.run_once() == 1
    handle = temporal_client.get_workflow_handle(command.workflow_id)
    first_run = (await handle.describe()).run_id
    # Redelivery after a lost start ACK must bind to the same execution.
    async with sessions() as session, session.begin():
        event = await session.scalar(select(OutboxEventRow).with_for_update())
        event.published_at = None
    assert await loop.run_once() == 1
    assert (await handle.describe()).run_id == first_run
    async with worker(temporal_client, activities):
        await asyncio.wait_for(runner.entered.wait(), 10)
    assert runner.stopped.is_set()
    # A replacement worker receives the retried Activity, never a second Workflow.
    activities._inspector._runner = FakeRunner(runner_result())
    async with worker(temporal_client, activities):
        result = await asyncio.wait_for(handle.result(), 45)
        assert result["status"] == "ready"
    assert (await repo.get(intent.id, TEST_USER.owner_hash)).attempt == 2
    async with sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(MediaInspectionRow))
            == 1
        )
    history = await handle.fetch_history()
    await Replayer(workflows=[InspectionWorkflow]).replay_workflow(history)
    # Source URL and encrypted envelopes never enter History.
    encoded = b"".join(event.SerializeToString() for event in history.events)
    assert URL.encode() not in encoded and b"url_ciphertext" not in encoded
    # A stale outbox event after successful completion cannot revive work.
    async with sessions() as session, session.begin():
        event = await session.scalar(select(OutboxEventRow).with_for_update())
        event.published_at = None
    assert await loop.run_once() == 1
    assert (await handle.describe()).run_id == first_run
    await service.cancel(intent.id, TEST_USER.owner_hash)
    assert await loop.run_once() == 1
    async with sessions() as session:
        pending = await session.scalar(
            select(func.count())
            .select_from(OutboxEventRow)
            .where(OutboxEventRow.published_at.is_(None))
        )
        assert pending == 0


async def test_cancel_outbox_interrupts_running_activity(
    postgres_engine, temporal_client
):
    runner = WaitingRunner()
    service, repo, activities, clock, sessions = components(postgres_engine, runner)
    intent = await service.create(URL, TEST_USER.owner_hash, "cancel")
    loop = dispatch(repo, sessions, clock, temporal_client)
    handle = temporal_client.get_workflow_handle(
        InspectionCommand(str(intent.id), 0).workflow_id
    )
    async with worker(temporal_client, activities):
        assert await loop.run_once() == 1
        await asyncio.wait_for(runner.entered.wait(), 10)
        await service.cancel(intent.id, TEST_USER.owner_hash)
        assert await loop.run_once() == 1
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), 15)
        assert runner.stopped.is_set()
    assert (await repo.get(intent.id, TEST_USER.owner_hash)).status == "cancelled"
    async with sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(MediaInspectionRow))
            == 0
        )
