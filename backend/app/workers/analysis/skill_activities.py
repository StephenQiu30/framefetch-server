"""Host execution for formal analysis tasks, with fenced calls and bounded renewal."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from app.core.config import Settings
from app.repositories.analysis.repository import SqlAlchemyAnalysisRepository
from app.repositories.analysis.repository_serialization import analysis_result_document
from app.services.analysis.models import AnalysisJobSnapshot, AnalysisPublish
from app.services.analysis.rules.enums import AnalysisStage
from app.services.analysis_execution.models import AnalysisExecutionOutput
from app.services.analysis_execution.monitor import AnalysisLeaseMonitor
from app.services.analysis_execution.ports import AnalysisExecutionRepository
from app.workers.analysis.skill_workflow import SkillCommand
from app.workers.analysis.utilities import utc_now
from temporalio import activity
from temporalio.exceptions import ApplicationError

_log = logging.getLogger(__name__)
_HEARTBEAT_DB_TIMEOUT_SECONDS = 15
_HEARTBEAT_INTERVAL_SECONDS = 5


class ClaimedSkillExecutor(Protocol):
    async def execute(
        self, job: AnalysisJobSnapshot, monitor: AnalysisLeaseMonitor
    ) -> AnalysisExecutionOutput: ...


@dataclass
class _State:
    job: AnalysisJobSnapshot | None = None
    monitor: AnalysisLeaseMonitor | None = None


class SkillActivities:
    def __init__(
        self,
        repository: SqlAlchemyAnalysisRepository,
        persistence: AnalysisExecutionRepository,
        executors: dict[tuple[str, str], ClaimedSkillExecutor],
        settings: Settings,
    ) -> None:
        self.repository, self.persistence, self.executors, self.settings = (
            repository,
            persistence,
            executors,
            settings,
        )
        self._model_slot = asyncio.Semaphore(1)

    @activity.defn(name="run_analysis_skill")
    async def run(self, command: SkillCommand) -> str:
        identifier, run_id = UUID(command.job_id), UUID(command.run_id)
        state = _State()
        parent = asyncio.current_task()
        heartbeat: asyncio.Task[None] | None = None
        acquired = False
        started = activity.info().started_time if activity.in_activity() else utc_now()
        execution_deadline = started + timedelta(seconds=command.timeout_seconds)
        try:
            waiting = await self.repository.get_job(identifier)
            if (
                waiting is None
                or waiting.run_id != run_id
                or waiting.run_no != command.run_no
            ):
                return "superseded"
            if waiting.status != "queued":
                return waiting.status
            executor = self.executors.get((waiting.input_kind, waiting.result_contract))
            if executor is None:
                return await self._close(command, "analysis_cli_unsupported")
            heartbeat = asyncio.create_task(self._heartbeat(command, state, parent))
            await asyncio.wait_for(
                self._model_slot.acquire(),
                timeout=max(0, (execution_deadline - utc_now()).total_seconds()),
            )
            acquired = True
            claimed = await self.repository.claim_run(
                identifier,
                run_id,
                command.run_no,
                command.workflow_id,
                utc_now(),
                timedelta(seconds=60),
            )
            if claimed is None:
                return "superseded"
            state.job = claimed
            if (
                hashlib.sha256(claimed.skill_instructions.encode()).hexdigest()
                != claimed.skill_instructions_sha256
            ):
                raise ValueError("frozen Skill method differs")
            state.monitor = AnalysisLeaseMonitor(
                repository=self.persistence,
                job_id=identifier,
                run_id=run_id,
                owner=command.workflow_id,
                attempt=claimed.attempt,
                clock=utc_now,
                lease_for=timedelta(seconds=60),
                interval=5,
                execution_deadline=execution_deadline,
            )
            async with asyncio.timeout(
                max(0, (execution_deadline - utc_now()).total_seconds())
            ):
                output = await executor.execute(claimed, state.monitor)
                await state.monitor.advance(AnalysisStage.VALIDATING, 90)
                if (
                    len(
                        json.dumps(
                            analysis_result_document(output.result), ensure_ascii=False
                        ).encode()
                    )
                    > 1024**2
                ):
                    raise ValueError("analysis result exceeds its JSON byte limit")
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
                current = await self.repository.get_job(identifier)
                if current is None or current.run_id != run_id:
                    return "superseded"
                saved = await self.repository.publish_result(
                    AnalysisPublish(
                        job_id=identifier,
                        run_id=run_id,
                        result=output.result,
                        lease_owner=command.workflow_id,
                        expected_version=current.version,
                        provider=output.provider,
                        model=output.model,
                        cli_version=output.cli_version,
                        now=utc_now(),
                    )
                )
                return saved.status
        except asyncio.CancelledError:
            await asyncio.shield(self._close(command, "worker_lost"))
            raise
        except (ValueError, TimeoutError):
            return await self._close(
                command,
                "invalid_model_output" if state.job is not None else "worker_lost",
            )
        except Exception as error:
            code = getattr(error, "code", None)
            if code:
                return await self._close(command, str(code))
            raise ApplicationError("Skill infrastructure unavailable") from None
        finally:
            if acquired:
                self._model_slot.release()
            if heartbeat is not None:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)

    @activity.defn(name="reconcile_analysis_skill")
    async def reconcile(self, command: SkillCommand) -> str:
        return await self._close(command, "worker_lost")

    async def _close(self, command: SkillCommand, code: str) -> str:
        saved = await self.repository.fail_run(
            UUID(command.job_id), UUID(command.run_id), error_code=code, now=utc_now()
        )
        return "superseded" if saved is None else saved.status

    async def _heartbeat(
        self, command: SkillCommand, state: _State, parent: asyncio.Task[str] | None
    ) -> None:
        while True:
            phase = "activity_heartbeat"
            try:
                activity.heartbeat()
                async with asyncio.timeout(_HEARTBEAT_DB_TIMEOUT_SECONDS):
                    phase = "read_job"
                    job = await self.repository.get_job(UUID(command.job_id))
                    if (
                        job is None
                        or job.run_id != UUID(command.run_id)
                        or job.status in {"cancelled", "failed", "succeeded"}
                    ):
                        if parent is not None:
                            parent.cancel()
                        return
                    if state.monitor is not None:
                        phase = "renew_lease"
                        await state.monitor.renew()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                _log.error(
                    json.dumps(
                        {
                            "event": "skill_heartbeat_failed",
                            "exception_type": type(error).__name__,
                            "job_id": command.job_id,
                            "run_id": command.run_id,
                            "phase": phase,
                        },
                        sort_keys=True,
                    )
                )
                if parent is not None:
                    parent.cancel()
                return
            await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
