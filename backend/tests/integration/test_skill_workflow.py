"""SkillWorkflow on a real Temporal server and PostgreSQL."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

from app.integrations.temporal_client import CommandPublisher
from app.models import AnalysisStepResultRow, ArtifactRow, OutboxEventRow
from app.repositories.analysis.execution import AnalysisExecutionPersistence
from app.repositories.analysis.repository import SqlAlchemyAnalysisRepository
from app.repositories.downloads.intent_repository import IntentRepository
from app.repositories.downloads.repository import SqlAlchemyDownloadRepository
from app.repositories.outbox_repository import SqlAlchemyOutboxRepository
from app.services.analysis_execution.models import VideoAnalysisRequest
from app.services.analysis_execution.service import AnalysisExecution
from app.workers.analysis.activities import SkillActivities
from app.workers.analysis.workflows import (
    SKILL_TASK_QUEUE,
    SkillCommand,
    SkillWorkflow,
)
from app.workers.outbox.loop import OutboxPublisherLoop
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from temporalio.worker import Replayer, Worker
from tests.unit.repositories.analysis.factories import analysis_command, seed_artifact
from tests.unit.workers.analysis.fakes import FakeLoader, settings
from tests.unit.workers.analysis.fixtures import valid_mapping

MARKER = "仅用于验证不进入 History 的模型输出"


def model_output() -> dict[str, object]:
    mapping = valid_mapping()
    mapping["summary"] = {"text": MARKER, "evidence_shot_ids": ["shot-a"]}
    return mapping


class CountingAnalyzer:
    def __init__(self) -> None:
        self.calls = 0

    async def analyze(self, request: VideoAnalysisRequest) -> object:
        self.calls += 1
        return model_output()


class HangingAnalyzer:
    def __init__(self) -> None:
        self.entered = asyncio.Event()

    async def analyze(self, request: VideoAnalysisRequest) -> object:
        self.entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def now() -> datetime:
    return datetime.now(UTC)


def activities(sessions, analyzer, workspace: Path) -> SkillActivities:
    persistence = AnalysisExecutionPersistence(
        SqlAlchemyAnalysisRepository(sessions), SqlAlchemyDownloadRepository(sessions)
    )
    execution = AnalysisExecution(
        repository=persistence,
        loader=FakeLoader(workspace),
        analyzer=analyzer,
        clock=now,
        settings=settings(),
    )
    return SkillActivities(execution, persistence, clock=now)


def worker(client, skill: SkillActivities) -> Worker:
    return Worker(
        client,
        task_queue=SKILL_TASK_QUEUE,
        workflows=[SkillWorkflow],
        activities=[skill.run_skill, skill.finish_skill],
        max_concurrent_activities=1,
        graceful_shutdown_timeout=timedelta(milliseconds=100),
        max_heartbeat_throttle_interval=timedelta(milliseconds=100),
    )


async def submit(sessions, client) -> SkillCommand:
    analyses = SqlAlchemyAnalysisRepository(sessions)
    source = await seed_artifact(sessions, now())
    async with sessions() as session, session.begin():
        # Match the 2-second timeline of the strict-result fixture.
        await session.execute(
            update(ArtifactRow)
            .where(ArtifactRow.id == source.artifact_id)
            .values(duration_ms=2_000)
        )
    command = analysis_command(source)
    await analyses.create_job_and_enqueue(command, now=now())
    loop = OutboxPublisherLoop(
        repository=SqlAlchemyOutboxRepository(sessions),
        publisher=CommandPublisher(
            AsyncMock(),
            IntentRepository(sessions),
            analyses,
            address=client.service_client.config.target_host,
            namespace="framefetch-test",
        ),
        publisher_id="test-publisher",
        clock=now,
    )
    assert await loop.run_once() == 1
    skill = SkillCommand(str(command.id), str(command.run_id), 1)
    first_run = (await client.get_workflow_handle(skill.workflow_id).describe()).run_id
    # Redelivery after a lost start ACK binds to the same execution.
    async with sessions() as session, session.begin():
        event = await session.scalar(select(OutboxEventRow).with_for_update())
        event.published_at = None
    assert await loop.run_once() == 1
    handle = client.get_workflow_handle(skill.workflow_id)
    assert (await handle.describe()).run_id == first_run
    return skill


async def step_rows(sessions) -> int:
    async with sessions() as session:
        return int(
            await session.scalar(
                select(func.count()).select_from(AnalysisStepResultRow)
            )
            or 0
        )


async def test_skill_run_publishes_once_and_keeps_model_output_out_of_history(
    postgres_engine, temporal_client, tmp_path: Path
) -> None:
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    command = await submit(sessions, temporal_client)
    analyzer = CountingAnalyzer()
    handle = temporal_client.get_workflow_handle(command.workflow_id)

    async with worker(temporal_client, activities(sessions, analyzer, tmp_path)):
        outcome = await asyncio.wait_for(handle.result(), 30)

    assert outcome["status"] == "publishing"
    assert analyzer.calls == 1
    stored = await SqlAlchemyAnalysisRepository(sessions).get_job(UUID(command.job_id))
    assert stored is not None and stored.stage == "publishing"
    # The report is persisted, so step payloads are gone with the run.
    assert await step_rows(sessions) == 0
    history = await handle.fetch_history()
    await Replayer(workflows=[SkillWorkflow]).replay_workflow(history)
    encoded = b"".join(event.SerializeToString() for event in history.events)
    assert MARKER.encode() not in encoded


async def test_lost_worker_mid_call_fails_as_unknown_outcome_without_second_call(
    postgres_engine, temporal_client, tmp_path: Path
) -> None:
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    command = await submit(sessions, temporal_client)
    handle = temporal_client.get_workflow_handle(command.workflow_id)
    hanging = HangingAnalyzer()

    async with worker(temporal_client, activities(sessions, hanging, tmp_path)):
        await asyncio.wait_for(hanging.entered.wait(), 10)
    # The worker is gone while the provider call was in flight.
    assert await step_rows(sessions) == 1

    replacement = CountingAnalyzer()
    async with worker(temporal_client, activities(sessions, replacement, tmp_path)):
        outcome = await asyncio.wait_for(handle.result(), 60)

    assert outcome["status"] == "failed"
    assert replacement.calls == 0
    job = await SqlAlchemyAnalysisRepository(sessions).get_job(UUID(command.job_id))
    assert job is not None
    assert (job.error_code, job.attempt) == ("analysis_outcome_unknown", 1)
    assert await step_rows(sessions) == 0
