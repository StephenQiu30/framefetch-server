from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.integrations.ai_cli.errors import AnalysisCliError
from app.services.analysis_execution.ports import ScreenplayRewriteAnalyzerSelection
from app.services.analysis_execution.screenplay_executor import (
    ScreenplayAnalysisExecutor,
)
from app.services.analysis_execution.screenplay_rewrite_executor import (
    ScreenplayRewriteExecutor,
)
from app.services.analysis_execution.screenplay_rewrite_models import (
    ScreenplayGlossaryRequest,
    ScreenplayRewriteChunkRequest,
)
from app.services.analysis_execution.screenplay_router import ScreenplayExecutionRouter
from app.services.analysis_execution.service import AnalysisExecution

from .fakes import NOW, FakeLoader, settings
from .screenplay_fakes import (
    SCREENPLAY_TEXT,
    FakeScreenplayAnalyzer,
    FakeScreenplayLoader,
    FakeScreenplayResolver,
    FakeVideoAnalyzer,
    ScreenplayRepository,
    screenplay_job_and_source,
)


class FakeRewriteAnalyzer:
    def __init__(self) -> None:
        self.glossary_requests: list[ScreenplayGlossaryRequest] = []
        self.chunk_requests: list[ScreenplayRewriteChunkRequest] = []
        self.invalid_call: int | None = None
        self.invalid_calls: set[int] = set()
        self.error_calls: dict[int, str] = {}
        self.omit_glossary_target = False
        self.rewritten_text = "Rewritten scene part.\n"
        self.retry_delays: list[float] = []

    async def build_screenplay_glossary(
        self, request: ScreenplayGlossaryRequest
    ) -> object:
        self.glossary_requests.append(request)
        return {
            "source_language": request.source_language,
            "target_language": request.target_language,
            "terms": [
                {"source": "林舟", "target": "Lin Zhou", "category": "character"}
            ],
            "style_rules": ["Preserve screenplay formatting."],
        }

    async def rewrite_screenplay_chunk(
        self, request: ScreenplayRewriteChunkRequest
    ) -> object:
        self.chunk_requests.append(request)
        call_no = len(self.chunk_requests)
        if code := self.error_calls.get(call_no):
            raise AnalysisCliError(
                code,
                no_model_execution=code == "analysis_provider_rate_limited",
                outcome_known=code
                in {"invalid_model_output", "analysis_resource_limit"},
            )
        scene_id = request.source_scene_id
        if self.invalid_call == call_no or call_no in self.invalid_calls:
            scene_id = "scene-invented"
        prefix = ""
        if not self.omit_glossary_target:
            prefix = "Lin Zhou " * request.source_text.count("林舟")
        return {
            "source_scene_id": scene_id,
            "part_no": request.part_no,
            "source_sha256": request.source_sha256,
            "target_language": request.target_language,
            "rewritten_text": prefix + self.rewritten_text,
            "change_summary": ["Rewrote the scene in natural English."],
        }


class FakeRewriteResolver:
    def __init__(self, analyzer: FakeRewriteAnalyzer) -> None:
        self.analyzer = analyzer
        self.calls = 0

    async def resolve_screenplay_rewrite(
        self,
    ) -> ScreenplayRewriteAnalyzerSelection:
        self.calls += 1
        return ScreenplayRewriteAnalyzerSelection(
            analyzer=self.analyzer,
            provider="controlled",
            model="controlled",
            cli_version="controlled",
        )


def build_rewrite_execution(
    root: Path,
    *,
    maximum: int = 20,
    max_chunks: int = 20,
    max_output: int = 10_000,
    max_glossary: int = 120_000,
    text: str | None = None,
) -> tuple[
    AnalysisExecution,
    ScreenplayRepository,
    FakeScreenplayLoader,
    FakeRewriteAnalyzer,
    FakeRewriteResolver,
]:
    screenplay_text = text if text is not None else SCREENPLAY_TEXT
    job, source = screenplay_job_and_source(text=screenplay_text)
    job = replace(
        job,
        result_contract="screenplay-rewrite",
        output_language="en-US",
        skill_id="screenplay-rewrite",
        skill_instructions="Rewrite the screenplay in natural English.",
    )
    repository = ScreenplayRepository(job, source)
    loader = FakeScreenplayLoader(root / "screenplay", text=screenplay_text)
    analyzer = FakeRewriteAnalyzer()

    async def record_retry_delay(delay: float) -> None:
        analyzer.retry_delays.append(delay)

    resolver = FakeRewriteResolver(analyzer)
    rewrite = ScreenplayRewriteExecutor(
        repository=repository,
        loader=loader,
        resolver=resolver,
        clock=lambda: NOW,
        max_glossary_characters=max_glossary,
        max_chunk_characters=maximum,
        max_chunks=max_chunks,
        context_characters=10,
        max_output_characters=max_output,
        chunk_call_attempts=2,
        chunk_retry_delay_seconds=0,
        sleep=record_retry_delay,
    )
    analysis = ScreenplayAnalysisExecutor(
        repository=repository,
        loader=loader,
        resolver=FakeScreenplayResolver(FakeScreenplayAnalyzer({})),
        clock=lambda: NOW,
        max_single_call_characters=120_000,
    )
    router = ScreenplayExecutionRouter(analysis=analysis, rewrite=rewrite)
    execution = AnalysisExecution(
        repository=repository,
        loader=FakeLoader(root / "video"),
        analyzer=FakeVideoAnalyzer(),
        screenplay_executor=router,
        clock=lambda: NOW,
        settings=settings(),
    )
    return execution, repository, loader, analyzer, resolver
