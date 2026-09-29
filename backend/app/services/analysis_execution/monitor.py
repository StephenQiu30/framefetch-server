from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from app.services.analysis.rules.enums import AnalysisStage
from app.services.analysis_execution.errors import (
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
    ) -> None:
        self._repository = repository
        self._job_id = job_id
        self._run_id = run_id
        self._owner = owner
        self._attempt = attempt
        self._clock = clock
        self._lease_for = lease_for
        self._interval = interval

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
        except (
            AnalysisLeaseLost,
            AnalysisPersistenceUnavailable,
            asyncio.CancelledError,
        ):
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

        The journal row is written before the call. Only a failure returned by
        the call itself proves the outcome, so only then is the row released;
        an interrupted call leaves it for the next attempt to report as unknown.
        """
        begun = await self._repository.begin_step(
            self._run_id, key, request_digest(request), now=self._clock()
        )
        if begun.status is AnalysisStepStatus.UNKNOWN:
            raise AnalysisOutcomeUnknown
        if begun.status is AnalysisStepStatus.REPLAY:
            await self.advance(stage, progress)
            return parse(begun.payload)

        async def guarded() -> tuple[bool, object]:
            try:
                return True, await call()
            except Exception as error:
                return False, error

        succeeded, payload = await self.run(guarded, stage=stage, progress=progress)
        try:
            if not succeeded:
                raise payload  # type: ignore[misc]
            value = parse(payload)
        except Exception:
            await self._repository.abandon_step(self._run_id, key)
            raise
        await self._repository.complete_step(
            self._run_id, key, payload, now=self._clock()
        )
        return value

    async def advance(self, stage: AnalysisStage, progress: int) -> None:
        try:
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
    if isinstance(value, (tuple, list)):
        return [_stable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _stable(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported model step request value: {type(value).__name__}")
