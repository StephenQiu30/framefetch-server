from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.services.analysis.models import AnalysisJobSnapshot
from app.services.analysis.rules.enums import (
    AnalysisErrorCode,
    AnalysisInputKind,
    AnalysisStage,
    AnalysisStatus,
)
from app.services.analysis.rules.errors import AnalysisValidationError
from app.services.analysis_execution.errors import (
    AnalysisLeaseLost,
    AnalysisOwnershipLost,
    AnalysisPersistenceRejected,
    AnalysisPersistenceUnavailable,
    AnalysisSourceUnavailable,
    classify_analysis_failure,
)
from app.services.analysis_execution.models import (
    AnalysisExecutionOutput,
    AnalysisExecutionSettings,
)
from app.services.analysis_execution.monitor import AnalysisLeaseMonitor
from app.services.analysis_execution.ports import (
    AnalysisExecutionRepository,
    AnalyzerResolver,
    ArtifactLoader,
    Clock,
    VideoAnalyzer,
)
from app.services.analysis_execution.transitions import AnalysisTransitions
from app.services.analysis_execution.video_executor import (
    StaticAnalyzerResolver,
    VideoAnalysisExecutor,
)

_LOGGER = logging.getLogger(__name__)


class ClaimedAnalysisExecutor(Protocol):
    async def execute(
        self, job: AnalysisJobSnapshot, monitor: AnalysisLeaseMonitor
    ) -> AnalysisExecutionOutput: ...


class AnalysisExecution:
    def __init__(
        self,
        *,
        repository: AnalysisExecutionRepository,
        loader: ArtifactLoader,
        analyzer: VideoAnalyzer | None = None,
        resolver: AnalyzerResolver | None = None,
        screenplay_executor: ClaimedAnalysisExecutor | None = None,
        clock: Clock,
        settings: AnalysisExecutionSettings,
    ) -> None:
        self._repository = repository
        if resolver is None:
            if analyzer is None:
                raise ValueError("an analyzer or resolver is required")
            resolver = StaticAnalyzerResolver(
                analyzer,
                provider=settings.provider,
                model=settings.model,
                cli_version=settings.cli_version,
            )
        self._clock = clock
        self._settings = settings
        self._transitions = AnalysisTransitions(repository, clock)
        self._executors: dict[AnalysisInputKind, ClaimedAnalysisExecutor] = {
            AnalysisInputKind.VIDEO: VideoAnalysisExecutor(
                repository=repository,
                loader=loader,
                resolver=resolver,
                clock=clock,
            )
        }
        if screenplay_executor is not None:
            self._executors[AnalysisInputKind.SCREENPLAY] = screenplay_executor

    async def execute(
        self, job_id: UUID, run_id: UUID, run_no: int, owner: str
    ) -> AnalysisJobSnapshot | None:
        """Execute one Workflow Activity attempt and return the resulting state.

        Persistence outages propagate so that Temporal retries the Activity;
        the replacement attempt takes over the same run.
        """
        claimed = await self._repository.claim_run(
            job_id, run_id, run_no, owner, self._clock(), self._settings.lease_for
        )
        if claimed is not None:
            await self._execute_claimed(claimed, owner)
        return await self._repository.get_job(job_id)

    async def _execute_claimed(self, job: AnalysisJobSnapshot, owner: str) -> None:
        monitor = self._monitor(job, owner)
        executor = self._executor(job.input_kind)
        if executor is None:
            await self._transitions.fail(
                job.id, owner, job.attempt, AnalysisErrorCode.CLI_UNSUPPORTED
            )
            return
        try:
            output = await executor.execute(job, monitor)
            await monitor.advance(AnalysisStage.VALIDATING, 90)
            current = await self._repository.get_job(job.id)
            if current is None or not _owns(current, owner, job.attempt, self._clock()):
                raise AnalysisLeaseLost
            await self._repository.publish_result(
                job.id,
                current.run_id,
                owner,
                current.version,
                output.result,
                output.provider,
                output.model,
                output.cli_version,
                self._clock(),
            )
        except (AnalysisLeaseLost, AnalysisOwnershipLost):
            return
        except AnalysisPersistenceRejected:
            await self._transitions.fail(
                job.id, owner, job.attempt, AnalysisErrorCode.INTERNAL_ERROR
            )
        except AnalysisSourceUnavailable:
            await self._transitions.fail(
                job.id, owner, job.attempt, AnalysisErrorCode.INPUT_ARTIFACT_UNAVAILABLE
            )
        except (AnalysisPersistenceUnavailable, asyncio.CancelledError):
            raise
        except AnalysisValidationError:
            await self._transitions.fail(
                job.id, owner, job.attempt, AnalysisErrorCode.INVALID_MODEL_OUTPUT
            )
        except Exception as error:
            _LOGGER.warning(
                "analysis execution failed job_id=%s attempt=%s exception_type=%s "
                "cause_type=%s code=%s",
                job.id,
                job.attempt,
                type(error).__name__,
                type(error.__cause__).__name__ if error.__cause__ else "none",
                getattr(error, "code", "none"),
            )
            await self._transitions.fail(
                job.id,
                owner,
                job.attempt,
                classify_analysis_failure(error, AnalysisStage.ANALYZING),
            )

    def _monitor(self, job: AnalysisJobSnapshot, owner: str) -> AnalysisLeaseMonitor:
        return AnalysisLeaseMonitor(
            repository=self._repository,
            job_id=job.id,
            run_id=job.run_id,
            owner=owner,
            attempt=job.attempt,
            clock=self._clock,
            lease_for=self._settings.lease_for,
            interval=self._settings.heartbeat_interval,
        )

    def _executor(self, input_kind: str) -> ClaimedAnalysisExecutor | None:
        try:
            return self._executors.get(AnalysisInputKind(input_kind))
        except ValueError:
            return None


def _owns(job: AnalysisJobSnapshot, owner: str, attempt: int, now: datetime) -> bool:
    return (
        job.status == AnalysisStatus.RUNNING.value
        and job.stage == AnalysisStage.VALIDATING.value
        and job.lease_owner == owner
        and job.attempt == attempt
        and job.lease_expires_at is not None
        and now < job.lease_expires_at
    )
