from pathlib import Path

import pytest
from app.services.analysis.rules.screenplay_results import ScreenplayRewriteResult

from .screenplay_rewrite_fakes import build_rewrite_execution


@pytest.mark.asyncio
async def test_rewrite_publishes_complete_ordered_source_bound_result(
    tmp_path: Path,
) -> None:
    execution, repository, loader, analyzer, resolver = build_rewrite_execution(
        tmp_path
    )
    job = repository.job

    result = await execution.execute(job.id, job.run_id, job.run_no, "run:1:1")

    assert result == repository.job
    result = repository.published[0]
    assert isinstance(result, ScreenplayRewriteResult)
    assert len(result.chunks) == len(analyzer.chunk_requests) > 1
    assert [
        (item.source_scene_id, item.part_no, item.source_sha256)
        for item in result.chunks
    ] == [
        (item.source_scene_id, item.part_no, item.source_sha256)
        for item in analyzer.chunk_requests
    ]
    assert result.source_scene_count == result.output_scene_count == 1
    assert result.target_language == "en-US"
    assert analyzer.glossary_requests[0].screenplay_text
    assert resolver.calls == 1
    assert loader.cleaned is True
    assert [stage for stage, _ in repository.heartbeats] == [
        "preparing",
        "analyzing",
        "analyzing",
        *("analyzing" for _ in analyzer.chunk_requests),
        "validating",
    ]


@pytest.mark.asyncio
async def test_rewrite_scales_glossary_extraction_for_long_screenplay(
    tmp_path: Path,
) -> None:
    text = "林舟 sees a change.\n" * 8_000
    execution, repository, _, analyzer, _ = build_rewrite_execution(
        tmp_path,
        maximum=8_000,
        max_chunks=128,
        max_glossary=20_000,
        max_output=100_000,
        text=text,
    )

    result = await execution.execute(
        repository.job.id,
        repository.job.run_id,
        repository.job.run_no,
        "run:1:1",
    )

    assert result == repository.job
    assert len(analyzer.glossary_requests) > 1
    assert all(
        len(request.screenplay_text) <= 20_000 for request in analyzer.glossary_requests
    )
    assert (
        "".join(request.screenplay_text for request in analyzer.glossary_requests)
        == text
    )
    result = repository.published[0]
    assert isinstance(result, ScreenplayRewriteResult)
    assert len(result.chunks) > 1


@pytest.mark.asyncio
async def test_rewrite_recovers_current_invalid_chunk_without_repeating_verified_chunks(
    tmp_path: Path,
) -> None:
    execution, repository, loader, analyzer, _ = build_rewrite_execution(tmp_path)
    analyzer.invalid_call = 2
    job = repository.job

    await execution.execute(job.id, job.run_id, job.run_no, "run:1:1")

    result = repository.published[0]
    assert isinstance(result, ScreenplayRewriteResult)
    assert repository.failures == []
    assert len(analyzer.chunk_requests) == len(result.chunks) + 1
    assert analyzer.chunk_requests[1] == analyzer.chunk_requests[2]
    assert analyzer.chunk_requests[0] != analyzer.chunk_requests[1]
    assert analyzer.retry_delays == [0.0]
    assert loader.cleaned is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_code",
    [
        "analysis_provider_rate_limited",
        "invalid_model_output",
    ],
)
async def test_rewrite_recovers_current_transient_chunk_in_same_attempt(
    tmp_path: Path, error_code: str
) -> None:
    execution, repository, _, analyzer, _ = build_rewrite_execution(tmp_path)
    analyzer.error_calls[2] = error_code
    job = repository.job

    await execution.execute(job.id, job.run_id, job.run_no, "run:1:1")

    result = repository.published[0]
    assert isinstance(result, ScreenplayRewriteResult)
    assert len(analyzer.chunk_requests) == len(result.chunks) + 1
    assert analyzer.chunk_requests[1] == analyzer.chunk_requests[2]
    assert analyzer.retry_delays == [0.0]


@pytest.mark.asyncio
async def test_rewrite_exhausts_current_chunk_without_partial_publish(
    tmp_path: Path,
) -> None:
    execution, repository, loader, analyzer, _ = build_rewrite_execution(tmp_path)
    analyzer.invalid_calls = {2, 3}
    job = repository.job

    await execution.execute(job.id, job.run_id, job.run_no, "run:1:1")

    assert repository.published == []
    assert repository.failures[0]["error_code"] == "invalid_model_output"
    assert repository.failures[0]["retryable"] is False
    assert len(analyzer.chunk_requests) == 3
    assert analyzer.chunk_requests[1] == analyzer.chunk_requests[2]
    assert analyzer.retry_delays == [0.0]
    assert loader.cleaned is True


@pytest.mark.asyncio
async def test_rewrite_does_not_retry_nonrecoverable_chunk_failure(
    tmp_path: Path,
) -> None:
    execution, repository, _, analyzer, _ = build_rewrite_execution(tmp_path)
    analyzer.error_calls[1] = "analysis_resource_limit"
    job = repository.job

    await execution.execute(job.id, job.run_id, job.run_no, "run:1:1")

    assert repository.published == []
    assert repository.failures[0]["error_code"] == "analysis_resource_limit"
    assert len(analyzer.chunk_requests) == 1
    assert analyzer.retry_delays == []


@pytest.mark.asyncio
@pytest.mark.parametrize("error_code", ["analysis_cli_timeout", "analysis_cli_failed"])
async def test_rewrite_stops_on_unknown_chunk_outcome(
    tmp_path: Path, error_code: str
) -> None:
    execution, repository, _, analyzer, _ = build_rewrite_execution(tmp_path)
    analyzer.error_calls[2] = error_code
    job = repository.job
    await execution.execute(job.id, job.run_id, job.run_no, "run:1:1")
    assert repository.published == []
    assert len(analyzer.chunk_requests) == 2
    assert analyzer.retry_delays == []
    assert repository.failures[0]["error_code"] == "analysis_outcome_unknown"
    assert repository.failures[0]["retryable"] is False
    assert repository.steps["rewrite-001"][0] == "started"


@pytest.mark.asyncio
async def test_rewrite_output_limit_fails_without_partial_publish(
    tmp_path: Path,
) -> None:
    execution, repository, loader, analyzer, _ = build_rewrite_execution(
        tmp_path, max_output=10
    )
    job = repository.job

    await execution.execute(job.id, job.run_id, job.run_no, "run:1:1")

    assert repository.published == []
    assert repository.failures[0]["error_code"] == "analysis_resource_limit"
    assert repository.failures[0]["retryable"] is False
    assert len(analyzer.chunk_requests) == 1
    assert loader.cleaned is True


@pytest.mark.asyncio
async def test_rewrite_glossary_drift_fails_without_partial_publish(
    tmp_path: Path,
) -> None:
    execution, repository, loader, analyzer, _ = build_rewrite_execution(tmp_path)
    analyzer.omit_glossary_target = True
    job = repository.job

    await execution.execute(job.id, job.run_id, job.run_no, "run:1:1")

    assert repository.published == []
    assert repository.failures[0]["error_code"] == "invalid_model_output"
    assert repository.failures[0]["retryable"] is False
    assert len(analyzer.chunk_requests) > 1
    assert loader.cleaned is True


@pytest.mark.asyncio
async def test_rewrite_chunk_limit_fails_before_model_resolution(
    tmp_path: Path,
) -> None:
    execution, repository, loader, analyzer, resolver = build_rewrite_execution(
        tmp_path, maximum=10, max_chunks=1
    )
    job = repository.job

    await execution.execute(job.id, job.run_id, job.run_no, "run:1:1")

    assert repository.published == []
    assert repository.failures[0]["error_code"] == "analysis_resource_limit"
    assert resolver.calls == 0
    assert analyzer.glossary_requests == []
    assert loader.cleaned is True
