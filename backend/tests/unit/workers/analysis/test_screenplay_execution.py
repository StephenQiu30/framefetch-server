import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from app.services.analysis.rules.screenplay_results import ScreenplayAnalysisResult
from app.services.analysis_execution.models import (
    ScreenplayAnalysisRequest,
    ScreenplayAnalysisSynthesisRequest,
    ScreenplaySceneSource,
)

from .fakes import FakeLoader
from .fixtures import valid_screenplay_mapping
from .screenplay_fakes import (
    FakeScreenplayAnalyzer,
    FakeScreenplayLoader,
    ScreenplayRepository,
    build_screenplay_execution,
    screenplay_job_and_source,
)


@pytest.mark.asyncio
async def test_screenplay_analysis_publishes_grounded_result(tmp_path: Path) -> None:
    job, source = screenplay_job_and_source()
    repository = ScreenplayRepository(job, source)
    loader = FakeScreenplayLoader(tmp_path / "screenplay")
    analyzer = FakeScreenplayAnalyzer(valid_screenplay_mapping())

    result = await build_screenplay_execution(
        repository, FakeLoader(tmp_path / "video"), loader, analyzer
    ).execute(job.id, job.run_id, job.run_no, "run:1:1")

    assert result == repository.job
    assert isinstance(repository.published[0], ScreenplayAnalysisResult)
    assert [stage for stage, _ in repository.heartbeats] == [
        "preparing",
        "analyzing",
        "analyzing",
        "validating",
    ]
    assert analyzer.requests[0].source_scene_ids == ("scene-1",)
    assert loader.cleaned is True


@pytest.mark.asyncio
async def test_screenplay_rewrite_stays_unsupported_without_model_call(
    tmp_path: Path,
) -> None:
    job, source = screenplay_job_and_source()
    job = replace(job, result_contract="screenplay-rewrite")
    repository = ScreenplayRepository(job, source)
    loader = FakeScreenplayLoader(tmp_path / "screenplay")
    analyzer = FakeScreenplayAnalyzer(valid_screenplay_mapping())

    await build_screenplay_execution(
        repository, FakeLoader(tmp_path / "video"), loader, analyzer
    ).execute(job.id, job.run_id, job.run_no, "run:1:1")

    assert repository.failures[0]["error_code"] == "analysis_cli_unsupported"
    assert analyzer.requests == []
    assert loader.calls == 0


@pytest.mark.asyncio
async def test_screenplay_over_single_call_limit_uses_chunks_and_synthesis(
    tmp_path: Path,
) -> None:
    text = "INT. A - DAY\n\n" + ("A" * 40) + "\nINT. B - NIGHT\n\n" + ("B" * 40) + "\n"
    second_start = text.index("INT. B")
    job, source = screenplay_job_and_source(character_count=len(text))
    source = replace(
        source,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        size_bytes=len(text.encode()),
        scenes=(
            ScreenplaySceneSource("scene-1", 0, second_start),
            ScreenplaySceneSource("scene-2", second_start, len(text)),
        ),
    )
    repository = ScreenplayRepository(job, source)
    loader = FakeScreenplayLoader(tmp_path / "screenplay", text)
    analyzer = ChunkedScreenplayAnalyzer()

    result = await build_screenplay_execution(
        repository,
        FakeLoader(tmp_path / "video"),
        loader,
        analyzer,
        maximum=max(second_start, len(text) - second_start),
    ).execute(job.id, job.run_id, job.run_no, "run:1:1")

    assert result == repository.job
    result = repository.published[0]
    assert isinstance(result, ScreenplayAnalysisResult)
    assert tuple(item.source_scene_id for item in result.scenes) == (
        "scene-1",
        "scene-2",
    )
    assert [request.source_scene_ids for request in analyzer.requests] == [
        ("scene-1",),
        ("scene-2",),
    ]
    assert len(analyzer.synthesis_requests) == 1
    assert loader.cleaned is True


@pytest.mark.asyncio
async def test_screenplay_scene_limit_uses_multiple_chunks(tmp_path: Path) -> None:
    text = ("x" * 121) + "\n"
    job, source = screenplay_job_and_source(character_count=len(text))
    source = replace(
        source,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        size_bytes=len(text.encode()),
        scenes=tuple(
            ScreenplaySceneSource(
                f"scene-{index + 1}",
                index,
                len(text) if index == 120 else index + 1,
            )
            for index in range(121)
        ),
    )
    repository = ScreenplayRepository(job, source)
    loader = FakeScreenplayLoader(tmp_path / "screenplay", text)
    analyzer = ChunkedScreenplayAnalyzer()

    result = await build_screenplay_execution(
        repository,
        FakeLoader(tmp_path / "video"),
        loader,
        analyzer,
    ).execute(job.id, job.run_id, job.run_no, "run:1:1")

    assert result == repository.job
    assert [len(request.source_scene_ids) for request in analyzer.requests] == [120, 1]
    assert len(analyzer.synthesis_requests) == 1


@pytest.mark.asyncio
async def test_screenplay_unknown_source_scene_retries_as_invalid_output(
    tmp_path: Path,
) -> None:
    job, source = screenplay_job_and_source()
    repository = ScreenplayRepository(job, source)
    payload = valid_screenplay_mapping()
    scenes = payload["scenes"]
    assert isinstance(scenes, list) and isinstance(scenes[0], dict)
    scenes[0]["source_scene_id"] = "invented-scene"

    await build_screenplay_execution(
        repository,
        FakeLoader(tmp_path / "video"),
        FakeScreenplayLoader(tmp_path / "screenplay"),
        FakeScreenplayAnalyzer(payload),
    ).execute(job.id, job.run_id, job.run_no, "run:1:1")

    assert repository.failures[0]["error_code"] == "invalid_model_output"
    assert repository.failures[0]["retryable"] is False


class ChunkedScreenplayAnalyzer(FakeScreenplayAnalyzer):
    def __init__(self) -> None:
        super().__init__({})

    async def analyze_screenplay(self, request: ScreenplayAnalysisRequest) -> object:
        self.requests.append(request)
        return _mapping(request.source_scene_ids)

    async def synthesize_screenplay_analysis(
        self, request: ScreenplayAnalysisSynthesisRequest
    ) -> object:
        self.synthesis_requests.append(request)
        payload = _mapping(request.source_scene_ids)
        payload.pop("scenes")
        return payload


def _mapping(scene_ids: tuple[str, ...]) -> dict[str, object]:
    payload = valid_screenplay_mapping()
    payload["scenes"] = [
        {
            "id": f"analysis-{scene_id}",
            "source_scene_id": scene_id,
            "purpose": "推进故事",
            "conflict": "目标受阻",
            "turn": "局势变化",
            "pacing": "紧凑",
            "findings": ["场景目标明确"],
        }
        for scene_id in scene_ids
    ]
    return payload
