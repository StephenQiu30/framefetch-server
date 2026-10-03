from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from app.services.analysis.models import AnalysisJobSnapshot
from app.services.analysis.rules.result_types import AnalysisResult
from app.services.analysis_execution.models import (
    AnalysisArtifactSource,
    AnalysisScreenplaySource,
    AnalysisStepBegin,
    LocalAnalysisArtifact,
    LocalScreenplayArtifact,
    ScreenplayAnalysisRequest,
    ScreenplayAnalysisSynthesisRequest,
    VideoAnalysisRequest,
)
from app.services.analysis_execution.screenplay_rewrite_models import (
    ScreenplayGlossaryRequest,
    ScreenplayRewriteChunkRequest,
)


class AnalysisExecutionRepository(Protocol):
    async def claim_run(
        self,
        job_id: UUID,
        run_id: UUID,
        run_no: int,
        owner: str,
        now: datetime,
        lease_for: timedelta,
    ) -> AnalysisJobSnapshot | None: ...

    async def get_job(self, job_id: UUID) -> AnalysisJobSnapshot | None: ...

    async def get_artifact_source(
        self, job: AnalysisJobSnapshot, now: datetime
    ) -> AnalysisArtifactSource: ...

    async def get_screenplay_source(
        self, job: AnalysisJobSnapshot, now: datetime
    ) -> AnalysisScreenplaySource: ...

    async def heartbeat(
        self,
        job_id: UUID,
        worker_id: str,
        attempt: int,
        *,
        stage: str,
        progress: int,
        now: datetime,
        lease_for: timedelta,
    ) -> bool: ...

    async def publish_result(
        self,
        job_id: UUID,
        run_id: UUID,
        worker_id: str,
        expected_version: int,
        result: AnalysisResult,
        provider: str,
        model: str,
        cli_version: str,
        now: datetime,
    ) -> None: ...

    async def complete_failure(
        self,
        job_id: UUID,
        worker_id: str,
        attempt: int,
        *,
        error_code: str,
        error_message: str,
        retryable: bool,
        now: datetime,
        retry_at: datetime | None,
    ) -> AnalysisJobSnapshot: ...

    async def begin_step(
        self,
        run_id: UUID,
        step_key: str,
        input_sha256: str,
        *,
        now: datetime,
        owner: str,
        attempt: int,
    ) -> AnalysisStepBegin: ...

    async def complete_step(
        self,
        run_id: UUID,
        step_key: str,
        payload: object,
        *,
        now: datetime,
        owner: str,
        attempt: int,
    ) -> None: ...

    async def abandon_step(
        self, run_id: UUID, step_key: str, *, now: datetime, owner: str, attempt: int
    ) -> None: ...

    async def fail_step(
        self,
        run_id: UUID,
        step_key: str,
        error_code: str,
        *,
        now: datetime,
        owner: str,
        attempt: int,
    ) -> None: ...

    async def bind_execution(
        self,
        run_id: UUID,
        binding: dict[str, object],
        *,
        owner: str,
        attempt: int,
        now: datetime,
        deadline: datetime,
    ) -> None: ...


class ArtifactLoader(Protocol):
    async def materialize(
        self,
        source: AnalysisArtifactSource,
        *,
        job_id: UUID,
        attempt: int,
    ) -> LocalAnalysisArtifact: ...

    async def cleanup(self, local: LocalAnalysisArtifact) -> None: ...


class ScreenplayArtifactLoader(Protocol):
    async def materialize(
        self,
        source: AnalysisScreenplaySource,
        *,
        job_id: UUID,
        attempt: int,
    ) -> LocalScreenplayArtifact: ...

    async def cleanup(self, local: LocalScreenplayArtifact) -> None: ...


class VideoAnalyzer(Protocol):
    async def analyze(self, request: VideoAnalysisRequest) -> object: ...


class ScreenplayAnalyzer(Protocol):
    async def analyze_screenplay(
        self, request: ScreenplayAnalysisRequest
    ) -> object: ...

    async def synthesize_screenplay_analysis(
        self, request: ScreenplayAnalysisSynthesisRequest
    ) -> object: ...


class ScreenplayRewriteAnalyzer(Protocol):
    async def build_screenplay_glossary(
        self, request: ScreenplayGlossaryRequest
    ) -> object: ...

    async def rewrite_screenplay_chunk(
        self, request: ScreenplayRewriteChunkRequest
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class AnalyzerSelection:
    analyzer: VideoAnalyzer
    provider: str
    model: str
    cli_version: str
    binding_sha256: str = ""


class AnalyzerResolver(Protocol):
    async def resolve(self) -> AnalyzerSelection: ...


@dataclass(frozen=True, slots=True)
class ScreenplayAnalyzerSelection:
    analyzer: ScreenplayAnalyzer
    provider: str
    model: str
    cli_version: str


class ScreenplayAnalyzerResolver(Protocol):
    async def resolve_screenplay(self) -> ScreenplayAnalyzerSelection: ...


@dataclass(frozen=True, slots=True)
class ScreenplayRewriteAnalyzerSelection:
    analyzer: ScreenplayRewriteAnalyzer
    provider: str
    model: str
    cli_version: str


class ScreenplayRewriteAnalyzerResolver(Protocol):
    async def resolve_screenplay_rewrite(
        self,
    ) -> ScreenplayRewriteAnalyzerSelection: ...


type Clock = Callable[[], datetime]
type AsyncOperation[ResultT] = Callable[[], Coroutine[Any, Any, ResultT]]
