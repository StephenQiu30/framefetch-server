from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.services.analysis.rules.enums import AnalysisStage
from app.services.analysis_execution.errors import (
    AnalysisExecutionError,
    AnalysisLeaseLost,
    AnalysisOutcomeUnknown,
    AnalysisOwnershipLost,
    AnalysisPersistenceUnavailable,
)
from app.services.analysis_execution.models import AnalysisStepStatus
from app.services.analysis_execution.ports import (
    AnalysisExecutionRepository,
    AsyncOperation,
    Clock,
)


class AnalysisLeaseMonitor:
    def __init__(
        self,
        *,
        repository: AnalysisExecutionRepository,
        job_id: UUID,
        run_id: UUID,
        owner: str,
        attempt: int,
        clock: Clock,
        lease_for: timedelta,
        interval: float,
        execution_deadline: datetime | None = None,
    ) -> None:
        self._repository = repository
        self._job_id = job_id
        self._run_id = run_id
        self._owner = owner
        self._attempt = attempt
        self._clock = clock
        self._lease_for = lease_for
        self._interval = interval
        self._execution_deadline = execution_deadline
        self._lock = asyncio.Lock()
        self._stage = AnalysisStage.PREPARING
        self._progress = 0

    async def run[ResultT](
        self,
        operation: AsyncOperation[ResultT],
        *,
        stage: AnalysisStage,
        progress: int,
    ) -> ResultT:
        await self.advance(stage, progress)
        task = asyncio.create_task(operation())
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=self._interval)
                if done:
                    return await task
                await self.advance(stage, progress)
        except BaseException:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise

    async def step[ResultT](
        self,
        key: str,
        request: object,
        call: Callable[[], Awaitable[object]],
        parse: Callable[[object], ResultT],
        *,
        stage: AnalysisStage,
        progress: int,
    ) -> ResultT:
        """Run one model call at most once per run; replay its saved payload.

        A returned exception does not prove that the provider did not execute.
        Persist received output before parsing; invalid output is also a paid
        result and must never be silently discarded and regenerated.
        """
        begun = await self._repository.begin_step(
            self._run_id,
            key,
            request_digest(request),
            now=self._clock(),
            owner=self._owner,
            attempt=self._attempt,
        )
        if begun.status is AnalysisStepStatus.UNKNOWN:
            raise AnalysisOutcomeUnknown
        if begun.status is AnalysisStepStatus.FAILED:
            raise AnalysisExecutionError(str(begun.payload))
        if begun.status is AnalysisStepStatus.REPLAY:
            await self.advance(stage, progress)
            return parse(begun.payload)

        async def invoke() -> object:
            return await call()

        try:
            payload = await self.run(invoke, stage=stage, progress=progress)
        except (
            AnalysisLeaseLost,
            AnalysisPersistenceUnavailable,
            asyncio.CancelledError,
        ):
            raise
        except Exception as error:
            if getattr(error, "no_model_execution", False) is True:
                await self._repository.abandon_step(
                    self._run_id,
                    key,
                    now=self._clock(),
                    owner=self._owner,
                    attempt=self._attempt,
                )
                raise
            if getattr(error, "outcome_known", False) is True:
                await self._repository.fail_step(
                    self._run_id,
                    key,
                    str(getattr(error, "code", "invalid_model_output")),
                    now=self._clock(),
                    owner=self._owner,
                    attempt=self._attempt,
                )
                raise
            raise AnalysisOutcomeUnknown from error
        await self._repository.complete_step(
            self._run_id,
            key,
            payload,
            now=self._clock(),
            owner=self._owner,
            attempt=self._attempt,
        )
        return parse(payload)

    def bounded_timeout(self, seconds: float) -> float:
        if self._execution_deadline is None:
            return seconds
        return max(
            0, min(seconds, (self._execution_deadline - self._clock()).total_seconds())
        )

    async def bind_execution(
        self, binding: dict[str, object], *, deadline_for: timedelta
    ) -> None:
        await self._repository.bind_execution(
            self._run_id,
            binding,
            owner=self._owner,
            attempt=self._attempt,
            now=self._clock(),
            deadline=min(self._clock() + deadline_for, self._execution_deadline)
            if self._execution_deadline is not None
            else self._clock() + deadline_for,
        )

    async def advance(self, stage: AnalysisStage, progress: int) -> None:
        async with self._lock:
            await self._renew(stage, progress)
            self._stage, self._progress = stage, progress

    async def renew(self) -> None:
        async with self._lock:
            await self._renew(self._stage, self._progress)

    async def _renew(self, stage: AnalysisStage, progress: int) -> None:
        try:
            async with asyncio.timeout(15):
                owned = await self._repository.heartbeat(
                    self._job_id,
                    self._owner,
                    self._attempt,
                    stage=stage.value,
                    progress=progress,
                    now=self._clock(),
                    lease_for=self._lease_for,
                )
        except AnalysisOwnershipLost as exc:
            raise AnalysisLeaseLost from exc
        except Exception as error:
            logging.getLogger(__name__).error(
                json.dumps(
                    {
                        "event": "skill_heartbeat_failed",
                        "exception_type": type(error).__name__,
                        "job_id": str(self._job_id),
                        "run_id": str(self._run_id),
                        "phase": "renew_lease",
                    },
                    sort_keys=True,
                )
            )
            raise
        if not owned:
            raise AnalysisLeaseLost


def request_digest(request: object) -> str:
    """Hash the stable request content; per-attempt workspace paths are excluded."""
    if not dataclasses.is_dataclass(request) or isinstance(request, type):
        raise TypeError("model step requests must be dataclass instances")
    encoded = json.dumps(
        {"type": type(request).__name__, "content": _stable(request)},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _stable(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _stable(getattr(value, field.name))
            for field in dataclasses.fields(value)
            if not isinstance(getattr(value, field.name), Path)
        }
    if isinstance(value, Path):
        return value.name
    if isinstance(value, (tuple, list)):
        return [_stable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _stable(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported model step request value: {type(value).__name__}")
