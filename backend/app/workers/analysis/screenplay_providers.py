from __future__ import annotations

from typing import cast

from app.integrations.ai_cli.errors import AnalysisCliError
from app.services.analysis_execution.ports import (
    AnalyzerResolver,
    ScreenplayAnalyzer,
    ScreenplayAnalyzerSelection,
    ScreenplayRewriteAnalyzer,
    ScreenplayRewriteAnalyzerSelection,
)


class ConfiguredScreenplayAnalyzerResolver:
    """Reuse provider selection while requiring a no-tool screenplay adapter."""

    def __init__(self, resolver: AnalyzerResolver) -> None:
        self._resolver = resolver

    async def resolve_screenplay(self) -> ScreenplayAnalyzerSelection:
        selection = await self._resolver.resolve()
        analyze = getattr(selection.analyzer, "analyze_screenplay", None)
        synthesize = getattr(selection.analyzer, "synthesize_screenplay_analysis", None)
        if not callable(analyze) or not callable(synthesize):
            raise AnalysisCliError("analysis_cli_unsupported")
        return ScreenplayAnalyzerSelection(
            analyzer=cast(ScreenplayAnalyzer, selection.analyzer),
            provider=selection.provider,
            model=selection.model,
            cli_version=selection.cli_version,
        )

    async def resolve_screenplay_rewrite(self) -> ScreenplayRewriteAnalyzerSelection:
        selection = await self._resolver.resolve()
        glossary = getattr(selection.analyzer, "build_screenplay_glossary", None)
        rewrite = getattr(selection.analyzer, "rewrite_screenplay_chunk", None)
        if not callable(glossary) or not callable(rewrite):
            raise AnalysisCliError("analysis_cli_unsupported")
        return ScreenplayRewriteAnalyzerSelection(
            analyzer=cast(ScreenplayRewriteAnalyzer, selection.analyzer),
            provider=selection.provider,
            model=selection.model,
            cli_version=selection.cli_version,
        )
