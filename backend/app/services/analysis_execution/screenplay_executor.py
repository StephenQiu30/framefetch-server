from __future__ import annotations

import asyncio
from contextlib import suppress
from functools import partial

from app.services.analysis.models import AnalysisJobSnapshot
from app.services.analysis.rules.enums import AnalysisResultContract, AnalysisStage
from app.services.analysis.rules.screenplay_parser import (
    parse_screenplay_analysis_result,
)
from app.services.analysis.rules.screenplay_results import ScreenplayAnalysisResult
from app.services.analysis_execution.errors import (
    AnalysisArtifactError,
    AnalysisExecutionError,
)
from app.services.analysis_execution.models import (
    SCREENPLAY_SINGLE_CALL_SCENE_LIMIT,
    AnalysisExecutionOutput,
    AnalysisScreenplaySource,
    LocalScreenplayArtifact,
    ScreenplayAnalysisSynthesisRequest,
)
from app.services.analysis_execution.monitor import AnalysisLeaseMonitor
from app.services.analysis_execution.ports import (
    AnalysisExecutionRepository,
    Clock,
    ScreenplayAnalyzerResolver,
    ScreenplayAnalyzerSelection,
    ScreenplayArtifactLoader,
)
from app.services.analysis_execution.screenplay_analysis_plan import (
    plan_screenplay_analysis,
)
from app.services.analysis_execution.screenplay_analysis_result import (
    build_analysis_request,
    combined_analysis_payload,
    synthesis_results_json,
)
from app.services.analysis_execution.screenplay_rewrite_result import (
    read_screenplay_text,
)

_SKILL_INSTRUCTION_ALLOWANCE = 8_000


class ScreenplayAnalysisExecutor:
    def __init__(
        self,
        *,
        repository: AnalysisExecutionRepository,
        loader: ScreenplayArtifactLoader,
        resolver: ScreenplayAnalyzerResolver,
        clock: Clock,
        max_single_call_characters: int,
        max_chunks: int = 128,
        max_synthesis_bytes: int = 2 * 1024**2,
    ) -> None:
        limits = (max_single_call_characters, max_chunks, max_synthesis_bytes)
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in limits
        ):
            raise ValueError("screenplay analysis limits must be positive")
        self._repository = repository
        self._loader = loader
        self._resolver = resolver
        self._clock = clock
        self._maximum = max_single_call_characters
        self._max_chunks = max_chunks
        self._max_synthesis_bytes = max_synthesis_bytes

    async def execute(
        self, job: AnalysisJobSnapshot, monitor: AnalysisLeaseMonitor
    ) -> AnalysisExecutionOutput:
        if job.result_contract != AnalysisResultContract.SCREENPLAY_ANALYSIS.value:
            raise AnalysisExecutionError("analysis_cli_unsupported")
        source = await self._repository.get_screenplay_source(job, self._clock())
        local: LocalScreenplayArtifact | None = None
        try:
            local = await monitor.run(
                lambda: self._loader.materialize(
                    source, job_id=job.id, attempt=job.attempt
                ),
                stage=AnalysisStage.PREPARING,
                progress=10,
            )
            text = await asyncio.to_thread(read_screenplay_text, local.screenplay)
            if len(text) != source.character_count:
                raise AnalysisArtifactError("artifact_integrity_failed")
            selection = await monitor.run(
                self._resolver.resolve_screenplay,
                stage=AnalysisStage.ANALYZING,
                progress=15,
            )
            maximum = _source_character_budget(
                self._maximum, job.skill_instructions, job.custom_prompt
            )
            if _fits_single_call(source.character_count, len(source.scenes), maximum):
                result = await self._single_call(
                    job, source, local, text, selection, monitor
                )
            else:
                result = await self._chunked(
                    job, source, local, text, selection, monitor, maximum
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
                    await self._loader.cleanup(local)

    async def _single_call(
        self,
        job: AnalysisJobSnapshot,
        source: AnalysisScreenplaySource,
        local: LocalScreenplayArtifact,
        text: str,
        selection: ScreenplayAnalyzerSelection,
        monitor: AnalysisLeaseMonitor,
    ) -> ScreenplayAnalysisResult:
        request = build_analysis_request(job, source, local, text, source.scenes)
        return await monitor.step(
            "screenplay",
            request,
            partial(selection.analyzer.analyze_screenplay, request),
            partial(
                parse_screenplay_analysis_result,
                expected_language=job.output_language,
                source_scene_ids=request.source_scene_ids,
            ),
            stage=AnalysisStage.ANALYZING,
            progress=70,
        )

    async def _chunked(
        self,
        job: AnalysisJobSnapshot,
        source: AnalysisScreenplaySource,
        local: LocalScreenplayArtifact,
        text: str,
        selection: ScreenplayAnalyzerSelection,
        monitor: AnalysisLeaseMonitor,
        maximum: int,
    ) -> ScreenplayAnalysisResult:
        plan = plan_screenplay_analysis(
            text,
            source.scenes,
            max_chunk_characters=maximum,
            max_chunk_scenes=SCREENPLAY_SINGLE_CALL_SCENE_LIMIT,
            max_chunks=self._max_chunks,
        )
        results: list[ScreenplayAnalysisResult] = []
        for index, chunk in enumerate(plan):
            chunk_request = build_analysis_request(
                job, source, local, chunk.text, chunk.scenes
            )
            results.append(
                await monitor.step(
                    f"chunk-{index:03d}",
                    chunk_request,
                    partial(selection.analyzer.analyze_screenplay, chunk_request),
                    partial(
                        parse_screenplay_analysis_result,
                        expected_language=job.output_language,
                        source_scene_ids=chunk_request.source_scene_ids,
                    ),
                    stage=AnalysisStage.ANALYZING,
                    progress=15 + ((index + 1) * 55 // len(plan)),
                )
            )
        synthesis_input = synthesis_results_json(
            tuple(results), maximum_bytes=self._max_synthesis_bytes
        )
        synthesis_request = ScreenplayAnalysisSynthesisRequest(
            screenplay=local.screenplay,
            workspace=local.workspace,
            chunk_results_json=synthesis_input,
            source_scene_ids=tuple(scene.id for scene in source.scenes),
            source_language=source.detected_language,
            output_language=job.output_language,
            skill_id=job.skill_id,
            skill_instructions=job.skill_instructions,
            custom_prompt=job.custom_prompt,
        )
        chunk_results = tuple(results)
        return await monitor.step(
            "synthesis",
            synthesis_request,
            partial(
                selection.analyzer.synthesize_screenplay_analysis, synthesis_request
            ),
            lambda summary: parse_screenplay_analysis_result(
                combined_analysis_payload(summary, chunk_results),
                expected_language=job.output_language,
                source_scene_ids=synthesis_request.source_scene_ids,
            ),
            stage=AnalysisStage.ANALYZING,
            progress=85,
        )


def _fits_single_call(characters: int, scenes: int, maximum: int) -> bool:
    return characters <= maximum and scenes <= SCREENPLAY_SINGLE_CALL_SCENE_LIMIT


def _source_character_budget(
    maximum: int, skill_instructions: str, custom_prompt: str | None
) -> int:
    available = (
        maximum
        + _SKILL_INSTRUCTION_ALLOWANCE
        - len(skill_instructions)
        - len(custom_prompt or "")
    )
    if available <= 0:
        raise AnalysisArtifactError("analysis_resource_limit")
    return min(maximum, available)
