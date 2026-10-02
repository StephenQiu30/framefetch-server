import pytest
from app.integrations.ai_cli.errors import AnalysisCliError
from app.services.analysis_execution.models import (
    ScreenplayAnalysisRequest,
    VideoAnalysisRequest,
)
from app.services.analysis_execution.ports import AnalyzerSelection, VideoAnalyzer
from app.workers.analysis.screenplay_providers import (
    ConfiguredScreenplayAnalyzerResolver,
)


class AnalyzerResolver:
    def __init__(self, analyzer: VideoAnalyzer) -> None:
        self.analyzer = analyzer

    async def resolve(self) -> AnalyzerSelection:
        return AnalyzerSelection(
            analyzer=self.analyzer,
            provider="provider",
            model="model",
            cli_version="version",
        )


class VideoOnlyAnalyzer:
    async def analyze(self, request: VideoAnalysisRequest) -> object:
        del request
        return {}


class NoToolScreenplayAnalyzer(VideoOnlyAnalyzer):
    async def analyze_screenplay(self, request: ScreenplayAnalysisRequest) -> object:
        del request
        return {}

    async def synthesize_screenplay_analysis(self, request: object) -> object:
        del request
        return {}

    async def build_screenplay_glossary(self, request: object) -> object:
        del request
        return {}

    async def rewrite_screenplay_chunk(self, request: object) -> object:
        del request
        return {}


@pytest.mark.asyncio
async def test_screenplay_resolver_preserves_supported_provider_metadata() -> None:
    resolver = ConfiguredScreenplayAnalyzerResolver(
        AnalyzerResolver(NoToolScreenplayAnalyzer())
    )

    selection = await resolver.resolve_screenplay()

    assert (selection.provider, selection.model, selection.cli_version) == (
        "provider",
        "model",
        "version",
    )

    rewrite = await resolver.resolve_screenplay_rewrite()
    assert (rewrite.provider, rewrite.model, rewrite.cli_version) == (
        "provider",
        "model",
        "version",
    )


@pytest.mark.asyncio
async def test_screenplay_resolver_rejects_video_only_provider() -> None:
    resolver = ConfiguredScreenplayAnalyzerResolver(
        AnalyzerResolver(VideoOnlyAnalyzer())
    )

    with pytest.raises(AnalysisCliError) as error:
        await resolver.resolve_screenplay()

    assert error.value.code == "analysis_cli_unsupported"

    with pytest.raises(AnalysisCliError) as rewrite_error:
        await resolver.resolve_screenplay_rewrite()

    assert rewrite_error.value.code == "analysis_cli_unsupported"
