"""Real Temporal transport, with an isolated CLI test server as the CI default."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from app.integrations.temporal_client import CommandPublisher
from app.models import MediaInspectionRow, OutboxEventRow
from app.repositories.analysis.repository import SqlAlchemyAnalysisRepository
from app.repositories.outbox_repository import SqlAlchemyOutboxRepository
from app.workers.download.workflows import InspectionCommand, InspectionWorkflow
from app.workers.outbox.loop import OutboxPublisherLoop
from sqlalchemy import func, select
from temporalio.client import WorkflowFailureError
from temporalio.worker import Replayer, Worker
from tests.integration.api.test_download_intent_routes import (
    URL,
    WaitingRunner,
    components,
)
from tests.integration.api.test_download_routes import TEST_USER
from tests.unit.services.fakes import FakeRunner
from tests.unit.services.test_inspect_media import runner_result


def worker(client, activities):
    return Worker(
        client,
        task_queue="ff-inspect",
        workflows=[InspectionWorkflow],
        activities=[
            activities.inspect_media,
            activities.finish_inspection,
        ],
        max_concurrent_activities=2,
        graceful_shutdown_timeout=timedelta(seconds=1),
        max_heartbeat_throttle_interval=timedelta(milliseconds=100),
    )


def dispatch(repo, sessions, clock, client):
    publisher = CommandPublisher(
        AsyncMock(),
        repo,
        SqlAlchemyAnalysisRepository(sessions),
        address=client.service_client.config.target_host,
        namespace="framefetch-test",
    )
    return OutboxPublisherLoop(
        repository=SqlAlchemyOutboxRepository(sessions),
        publisher=publisher,
        publisher_id="test-publisher",
        clock=lambda: clock[0],
    )


async def test_start_ack_loss_restart_does_not_resubmit_unknown_platform_execution(
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
    # SDK redelivery reconciles the original operation; a missing receipt cannot
    # authorize another platform call even when a new worker is available.
    replacement = FakeRunner(runner_result())
    activities._inspector._runner = replacement
    async with worker(temporal_client, activities):
        result = await asyncio.wait_for(handle.result(), 45)
        assert result["status"] == "failed"
    state = await repo.get(intent.id, TEST_USER.owner_hash)
    assert state.attempt == 1
    assert state.latest_failure.failure_class.value == "outcome_unknown"
    assert replacement.seen == []
    async with sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(MediaInspectionRow))
            == 0
        )
    history = await handle.fetch_history()
    await Replayer(workflows=[InspectionWorkflow]).replay_workflow(history)
    # Source URL and encrypted envelopes never enter History.
    encoded = b"".join(event.SerializeToString() for event in history.events)
    assert URL.encode() not in encoded and b"url_ciphertext" not in encoded
    # A stale outbox event after terminal reconciliation cannot revive work.
    async with sessions() as session, session.begin():
        event = await session.scalar(select(OutboxEventRow).with_for_update())
        event.published_at = None
    assert await loop.run_once() == 1
    assert (await handle.describe()).run_id == first_run
    await service.cancel(intent.id, TEST_USER.owner_hash)
    assert await loop.run_once() == 0  # A terminal intent needs no cancel delivery.
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


async def test_lost_activity_reply_recovers_original_receipt_and_commits_once(
    postgres_engine, temporal_client
):
    class LostReplyRunner(FakeRunner):
        async def inspect(self, url, **kwargs):
            await super().inspect(url, **kwargs)
            raise RuntimeError("transport reply lost after platform completion")

    runner = LostReplyRunner(runner_result())
    service, repo, activities, clock, sessions = components(postgres_engine, runner)
    intent = await service.create(URL, TEST_USER.owner_hash, "lost-reply")
    loop = dispatch(repo, sessions, clock, temporal_client)
    handle = temporal_client.get_workflow_handle(
        InspectionCommand(str(intent.id), 0).workflow_id
    )
    async with worker(temporal_client, activities):
        assert await loop.run_once() == 1
        result = await asyncio.wait_for(handle.result(), 15)
    assert result["status"] == "ready"
    assert (await repo.get(intent.id, TEST_USER.owner_hash)).attempt == 1
    assert runner.seen == [URL]
    assert await runner_result_count(sessions) == 1
    await Replayer(workflows=[InspectionWorkflow]).replay_workflow(
        await handle.fetch_history()
    )


async def test_automatic_session_wait_survives_worker_restart_without_user_command(
    postgres_engine, temporal_client
):
    from datetime import UTC, datetime

    from tests.integration.api.test_download_intent_routes import PreparingSessionRunner

    runner = PreparingSessionRunner()
    runner.waits = 3
    service, repo, activities, clock, sessions = components(
        postgres_engine, runner, operator_providers=frozenset({"youtube"})
    )
    clock[0] = datetime.now(UTC)
    intent = await service.create(URL, TEST_USER.owner_hash, "automatic-wait")
    loop = dispatch(repo, sessions, clock, temporal_client)
    handle = temporal_client.get_workflow_handle(
        InspectionCommand(str(intent.id), 0).workflow_id
    )
    async with worker(temporal_client, activities):
        assert await loop.run_once() == 1
        async with asyncio.timeout(15):
            while True:
                waiting = await repo.get(intent.id, TEST_USER.owner_hash)
                if waiting.status == "retry_wait":
                    break
                await asyncio.sleep(0.05)
        assert waiting.operation_id is None and waiting.attempt == 0
        assert waiting.deadline == intent.deadline
    # Temporal's timer is durable; no login/resume write or new outbox is needed.
    clock[0] = waiting.retry_at
    async with worker(temporal_client, activities):
        assert await loop.run_once() == 0
        result = await asyncio.wait_for(handle.result(), 25)
    assert result["status"] == "ready"
    state = await repo.get(intent.id, TEST_USER.owner_hash)
    assert (
        state.attempt == 1
        and state.generation == 0
        and state.deadline == intent.deadline
    )
    assert await runner_result_count(sessions) == 1
    await Replayer(workflows=[InspectionWorkflow]).replay_workflow(
        await handle.fetch_history()
    )
    async with sessions() as session, session.begin():
        event = await session.scalar(
            select(OutboxEventRow).where(
                OutboxEventRow.event_type == "download.intent.requested"
            )
        )
        event.published_at = None
    assert await loop.run_once() == 1
    assert await runner_result_count(sessions) == 1


async def runner_result_count(sessions):
    async with sessions() as session:
        return await session.scalar(
            select(func.count()).select_from(MediaInspectionRow)
        )
