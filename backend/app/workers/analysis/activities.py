"""Skill run execution and reconciliation, outside Workflow replay."""

from __future__ import annotations

import asyncio
from uuid import UUID

from app.repositories.analysis.execution import AnalysisExecutionPersistence
from app.services.analysis.models import AnalysisJobSnapshot
from app.services.analysis.rules.enums import AnalysisErrorCode, AnalysisStage
from app.services.analysis_execution.ports import Clock
from app.services.analysis_execution.service import AnalysisExecution
from app.workers.analysis.workflows import SkillCommand, SkillOutcome
from temporalio import activity
from temporalio.exceptions import ApplicationError as TemporalApplicationError

_FINISHED = {"succeeded", "failed", "cancelled"}


class SkillActivities:
    def __init__(
        self,
        execution: AnalysisExecution,
        repository: AnalysisExecutionPersistence,
        *,
        clock: Clock,
    ) -> None:
        self._execution = execution
        self._repository = repository
        self._clock = clock

    @activity.defn(name="run_skill")
    async def run_skill(self, command: SkillCommand) -> SkillOutcome:
        info = activity.info()
        owner = f"{info.workflow_run_id}:{info.activity_id}:{info.attempt}"
        heartbeat = asyncio.create_task(self._heartbeat())
        try:
            job = await self._execution.execute(
                UUID(command.job_id), UUID(command.run_id), command.run_no, owner
            )
            return await self._settle(command, job)
        except asyncio.CancelledError:
            # Cancelling the execution stops the provider call and its workspace.
            raise
        except Exception:
            # SDK failure serialization must never contain DB URLs or model output.
            raise TemporalApplicationError(
                "analysis infrastructure unavailable", type="AnalysisInfrastructure"
            ) from None
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _heartbeat(self) -> None:
        while True:
            activity.heartbeat()
            await asyncio.sleep(5)

    @activity.defn(name="finish_skill")
    async def finish_skill(self, command: SkillCommand) -> SkillOutcome:
        """Close a run after its attempts were lost; never re-invokes a model."""
        try:
            run_id = UUID(command.run_id)
            code = (
                AnalysisErrorCode.OUTCOME_UNKNOWN
                if await self._repository.has_started_step(run_id)
                else AnalysisErrorCode.WORKER_LOST
            )
            job = await self._repository.fail_run(
                UUID(command.job_id), run_id, error_code=code.value, now=self._clock()
            )
            return await self._settle(command, job)
        except Exception:
            raise TemporalApplicationError(
                "analysis reconciliation unavailable", type="AnalysisInfrastructure"
            ) from None

    async def _settle(
        self, command: SkillCommand, job: AnalysisJobSnapshot | None
    ) -> SkillOutcome:
        outcome = skill_outcome(command, job)
        if outcome.status in _FINISHED | {"publishing", "deleted", "superseded"}:
            # The report is persisted or the run is over: step payloads are no
            # longer needed and must not outlive the run.
            await self._repository.purge_steps(UUID(command.run_id))
        return outcome


def skill_outcome(
    command: SkillCommand, job: AnalysisJobSnapshot | None
) -> SkillOutcome:
    if job is None:
        return SkillOutcome("deleted")
    if str(job.run_id) != command.run_id:
        return SkillOutcome("superseded")
    if job.status == "running" and job.stage == AnalysisStage.PUBLISHING.value:
        return SkillOutcome("publishing")
    return SkillOutcome(job.status, job.retry_at.timestamp() if job.retry_at else None)
