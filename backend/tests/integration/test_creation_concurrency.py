"""A held model call does not hold local work or reserve waiting model calls."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

from app.core.config import Settings
from app.repositories.creation import CreationRepository
from app.services.analysis_execution.ports import AnalyzerSelection
from app.services.creation.catalog import get_capability
from app.services.creation.models import (
    CreationBudget,
    CreationConfirmRequest,
    CreationMaterialCreateRequest,
    CreationTaskCreateRequest,
)
from app.workers.analysis.creation_activities import CreationActivities
from app.workers.analysis.creation_workflow import CreationCommand, CreationWorkflow
from sqlalchemy.ext.asyncio import async_sessionmaker
from temporalio.api.enums.v1 import PendingActivityState
from temporalio.worker import Worker

OWNER = "a" * 64


class HeldGenerator:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = self.active = self.max_active = 0

    async def generate_content(self, request):
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.started.set()
        try:
            await self.release.wait()
            return {
                "body": "受控候选，等待人工核查。",
                "summary": "",
                "evidence": [],
                "media_evidence": [],
                "warnings": [],
                "structured": {
                    "sections": [],
                    "characters": [],
                    "findings": [],
                    "unresolved": [],
                },
            }
        finally:
            self.active -= 1


class Resolver:
    def __init__(self, generator):
        self.generator = generator

    async def resolve(self):
        return AnalyzerSelection(
            self.generator, "controlled", "controlled", "controlled", "a" * 64
        )


async def test_slow_model_does_not_block_local_or_charge_waiting_cancelled_task(
    postgres_engine, temporal_client, tmp_path: Path
):
    repository = CreationRepository(
        async_sessionmaker(postgres_engine, expire_on_commit=False)
    )
    source = await repository.create_material(
        OWNER,
        "source",
        CreationMaterialCreateRequest(
            kind="text",
            title="原创源",
            text="保留原文。\r\n第二段。",
            rights_statement="本人原创",
        ),
    )
    await repository.confirm_material(
        source.id,
        OWNER,
        CreationConfirmRequest(expected_revision_id=source.current_revision.id),
    )

    async def task(skill_id, key):
        return await repository.create_task(
            OWNER,
            key,
            CreationTaskCreateRequest(
                skill_id=skill_id,
                material_revision_ids=(source.current_revision.id,),
                budget=CreationBudget(max_calls=1),
            ),
            get_capability(skill_id).method_sha256,
        )

    first = await task("article-write", "first-model")
    cancelled = await task("article-write", "cancelled-model")
    later = await task("article-write", "later-model")
    lost = await task("article-write", "lost-before-claim")
    local = await task("article-edit", "local-format")
    generator = HeldGenerator()
    activities = CreationActivities(
        repository,
        Resolver(generator),
        AsyncMock(),
        Settings(_env_file=None, analysis_workspace_root=tmp_path),
    )
    queue = "creation-concurrency-" + str(uuid4())
    async with Worker(
        temporal_client,
        task_queue=queue,
        workflows=[CreationWorkflow],
        activities=[activities.run, activities.reconcile],
        max_concurrent_activities=8,
    ):
        try:

            async def start(value):
                command = CreationCommand(str(value.id), 1)
                return await temporal_client.start_workflow(
                    CreationWorkflow.run,
                    command,
                    id=command.workflow_id,
                    task_queue=queue,
                )

            first_handle = await start(first)
            await asyncio.wait_for(generator.started.wait(), 10)
            cancelled_handle = await start(cancelled)
            later_handle = await start(later)
            lost_handle = await start(lost)

            # Both model activities are running but waiting before claim/reservation.
            for handle in (cancelled_handle, later_handle, lost_handle):
                async with asyncio.timeout(10):
                    while True:
                        description = await handle.describe()
                        pending = description.raw_description.pending_activities
                        if (
                            pending
                            and pending[0].state
                            == PendingActivityState.PENDING_ACTIVITY_STATE_STARTED
                        ):
                            break
                        await asyncio.sleep(0.05)
            for value in (cancelled, later, lost):
                waiting = await repository.get_task(value.id, OWNER)
                assert waiting.status.value == "queued"
                assert waiting.usage.calls_reserved == waiting.usage.calls_used == 0
                assert waiting.usage.tokens_reserved == 0

            local_handle = await start(local)
            assert (
                await asyncio.wait_for(local_handle.result(), 10)
                == "awaiting_confirmation"
            )
            local_result = await repository.get_task(local.id, OWNER)
            assert local_result.revision.text == "保留原文。\n第二段。"
            assert (
                local_result.usage.calls_reserved == local_result.usage.calls_used == 0
            )
            assert generator.calls == generator.active == 1
            assert not generator.release.is_set()

            await repository.cancel_task(cancelled.id, OWNER)
            assert await asyncio.wait_for(cancelled_handle.result(), 10) == "cancelled"
            stopped = await repository.get_task(cancelled.id, OWNER)
            assert stopped.usage.calls_reserved == stopped.usage.calls_used == 0
            assert stopped.usage.unknown_operations == 0
            assert generator.calls == 1

            lost_command = CreationCommand(str(lost.id), 1)
            wrong_attempt = await repository.fail_task(
                lost.id, f"creation/{lost.id}/2", "analysis_worker_lost"
            )
            assert wrong_attempt.status.value == "queued"
            wrong_failure = await repository.fail_task(
                lost.id, lost_command.workflow_id, "creation_execution_failed"
            )
            assert wrong_failure.status.value == "queued"
            assert await activities.reconcile(lost_command) == "failed"
            lost_result = await repository.get_task(lost.id, OWNER)
            assert lost_result.usage.calls_reserved == lost_result.usage.calls_used == 0
            assert lost_result.usage.unknown_operations == 0

            generator.release.set()
            assert (
                await asyncio.wait_for(first_handle.result(), 10)
                == "awaiting_confirmation"
            )
            assert (
                await asyncio.wait_for(later_handle.result(), 10)
                == "awaiting_confirmation"
            )
            assert generator.calls == 2 and generator.max_active == 1
            assert await asyncio.wait_for(lost_handle.result(), 10) == "failed"
            for value in (first, later):
                completed = await repository.get_task(value.id, OWNER)
                assert completed.usage.calls_used == 1
                assert (
                    completed.usage.calls_reserved
                    == completed.usage.unknown_operations
                    == 0
                )
            retried = await repository.retry_task(
                lost.id, OWNER, "explicit-unsent-retry"
            )
            assert retried.attempt == 2 and retried.status.value == "queued"
            assert retried.budget.max_calls == 1 and retried.usage.calls_used == 0
            assert await activities.reconcile(lost_command) == "superseded"
            assert (await repository.get_task(lost.id, OWNER)).status.value == "queued"
        finally:
            generator.release.set()
