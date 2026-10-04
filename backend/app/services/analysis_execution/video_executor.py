from __future__ import annotations

from contextlib import suppress
from functools import partial

from app.services.analysis.models import AnalysisJobSnapshot
from app.services.analysis.rules.enums import AnalysisResultContract, AnalysisStage
from app.services.analysis.rules.result_models import AnalysisMedia
from app.services.analysis.rules.result_parser import parse_analysis_result
from app.services.analysis_execution.editorial_plan import has_stage
from app.services.analysis_execution.models import (
    AnalysisExecutionOutput,
    LocalAnalysisArtifact,
    VideoAnalysisRequest,
)
from app.services.analysis_execution.monitor import AnalysisLeaseMonitor
from app.services.analysis_execution.ports import (
    AnalysisExecutionRepository,
    AnalyzerResolver,
    AnalyzerSelection,
    ArtifactLoader,
    Clock,
    VideoAnalyzer,
)
from app.services.analysis_execution.video_editorial import execute_video_editorial
from app.services.analysis_execution.video_observations import log_video_observations


class VideoAnalysisExecutor:
    def __init__(
        self,
        *,
        repository: AnalysisExecutionRepository,
        loader: ArtifactLoader,
        resolver: AnalyzerResolver,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._loader = loader
        self._resolver = resolver
        self._clock = clock

    async def execute(
        self, job: AnalysisJobSnapshot, monitor: AnalysisLeaseMonitor
    ) -> AnalysisExecutionOutput:
        local: LocalAnalysisArtifact | None = None
        try:
            source = await self._repository.get_artifact_source(job, self._clock())
            local = await monitor.run(
                lambda: self._loader.materialize(
                    source, job_id=job.id, attempt=job.attempt
                ),
                stage=AnalysisStage.PREPARING,
                progress=10,
            )
            request = VideoAnalysisRequest(
                artifact=local.artifact,
                workspace=local.workspace,
                duration_ms=source.duration_ms,
                size_bytes=source.size_bytes,
                container=source.container,
                output_language=job.output_language,
                skill_id=job.skill_id,
                skill_instructions=job.skill_instructions,
                result_contract=AnalysisResultContract(job.result_contract),
                custom_prompt=job.custom_prompt,
            )
            selection = await monitor.run(
                self._resolver.resolve, stage=AnalysisStage.PREPARING, progress=15
            )
            media = AnalysisMedia(
                duration_ms=source.duration_ms,
                container=source.container,
                size_bytes=source.size_bytes,
            )
            if has_stage(job.skill_instructions, "plan"):
                editorial = await execute_video_editorial(
                    job, request, selection, monitor, media
                )
                return AnalysisExecutionOutput(
                    editorial,
                    selection.provider,
                    selection.model,
                    selection.cli_version,
                )
            result = await monitor.step(
                "video",
                request,
                partial(selection.analyzer.analyze, request),
                lambda payload: parse_analysis_result(
                    payload,
                    media,
                    expected_language=job.output_language,
                    result_contract=job.result_contract,
                ),
                stage=AnalysisStage.ANALYZING,
                progress=70,
            )
            return AnalysisExecutionOutput(
                result=result,
                provider=selection.provider,
                model=selection.model,
                cli_version=selection.cli_version,
            )
        finally:
            if local is not None:
                with suppress(Exception):
                    log_video_observations(local.workspace, job)
                with suppress(Exception):
                    await self._loader.cleanup(local)


class StaticAnalyzerResolver:
    def __init__(
        self,
        analyzer: VideoAnalyzer,
        *,
        provider: str,
        model: str,
        cli_version: str,
    ) -> None:
        self._selection = AnalyzerSelection(
            analyzer=analyzer,
            provider=provider,
            model=model,
            cli_version=cli_version,
        )

    async def resolve(self) -> AnalyzerSelection:
        return self._selection
