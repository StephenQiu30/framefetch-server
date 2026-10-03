from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from app.services.analysis_execution.errors import AnalysisPersistenceRejected
from app.services.analysis_execution.models import VideoAnalysisRequest
from app.services.analysis_execution.service import AnalysisExecution

from .fakes import (
    NOW,
    FakeLoader,
    FakeRepository,
    running_job,
    settings,
)
from .fixtures import valid_mapping

OWNER = "run:1:1"


class FakeAnalyzer:
    def __init__(self, output: object) -> None:
        self.output = output

    async def analyze(self, request: VideoAnalysisRequest) -> object:
        if isinstance(self.output, BaseException):
            raise self.output
        return self.output


class BlockingAnalyzer:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def analyze(self, request: VideoAnalysisRequest) -> object:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("unreachable")


class SlowAnalyzer:
    def __init__(self, output: object) -> None:
        self.output = output

    async def analyze(self, request: VideoAnalysisRequest) -> object:
        await asyncio.sleep(0.035)
        return self.output


class ProviderFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        self.no_model_execution = code == "analysis_provider_rate_limited"
        super().__init__(code)


def execution(
    repository: FakeRepository,
    loader: FakeLoader,
    *,
    analyzer: object,
) -> AnalysisExecution:
    return AnalysisExecution(
        repository=repository,  # type: ignore[arg-type]
        loader=loader,
        analyzer=analyzer,  # type: ignore[arg-type]
        clock=lambda: NOW,
        settings=settings(),
    )


@pytest.mark.asyncio
async def test_success_runs_linear_stages_publishes_and_cleans(tmp_path: Path) -> None:
    repository = FakeRepository(running_job())
    loader = FakeLoader(tmp_path)

    result = await execution(
        repository, loader, analyzer=FakeAnalyzer(valid_mapping())
    ).execute(
        repository.job.id,
        repository.job.run_id,
        repository.job.run_no,
        OWNER,
    )

    assert result == repository.job
    assert [stage for stage, _ in repository.heartbeats] == [
        "preparing",
        "analyzing",
        "analyzing",
        "validating",
    ]
    assert repository.job.status == "succeeded"
    assert len(repository.published) == 1
    assert loader.cleaned is True


@pytest.mark.asyncio
async def test_healthy_long_analysis_renews_lease_until_completion(
    tmp_path: Path,
) -> None:
    repository = FakeRepository(running_job())
    loader = FakeLoader(tmp_path)

    result = await execution(
        repository, loader, analyzer=SlowAnalyzer(valid_mapping())
    ).execute(
        repository.job.id,
        repository.job.run_id,
        repository.job.run_no,
        OWNER,
    )

    analyzing_heartbeats = [
        progress for stage, progress in repository.heartbeats if stage == "analyzing"
    ]
    assert result == repository.job
    assert len(analyzing_heartbeats) >= 3
    assert repository.job.status == "succeeded"


@pytest.mark.asyncio
async def test_rejected_result_persistence_fails_without_waiting_for_lease_expiry(
    tmp_path: Path,
) -> None:
    repository = FakeRepository(running_job())
    repository.publish_error = AnalysisPersistenceRejected("invalid result constraint")
    loader = FakeLoader(tmp_path)

    result = await execution(
        repository, loader, analyzer=FakeAnalyzer(valid_mapping())
    ).execute(
        repository.job.id,
        repository.job.run_id,
        repository.job.run_no,
        OWNER,
    )

    assert result == repository.job
    assert repository.job.status == "failed"
    assert repository.failures[0]["error_code"] == "internal_error"


@pytest.mark.asyncio
async def test_cancelled_lease_cancels_active_provider_and_cleans(
    tmp_path: Path,
) -> None:
    repository = FakeRepository(running_job())
    repository.heartbeat_failure_stage = "analyzing"
    loader = FakeLoader(tmp_path)
    analyzer = BlockingAnalyzer()

    result = await execution(repository, loader, analyzer=analyzer).execute(
        repository.job.id,
        repository.job.run_id,
        repository.job.run_no,
        OWNER,
    )

    assert analyzer.started.is_set()
    assert analyzer.cancelled is True
    assert repository.job.status == "cancelled"
    assert result == repository.job
    assert loader.cleaned is True


@pytest.mark.asyncio
async def test_rate_limit_records_retry_and_cleans(tmp_path: Path) -> None:
    repository = FakeRepository(running_job())
    loader = FakeLoader(tmp_path)
    result = await execution(
        repository,
        loader,
        analyzer=FakeAnalyzer(ProviderFailure("analysis_provider_rate_limited")),
    ).execute(
        repository.job.id,
        repository.job.run_id,
        repository.job.run_no,
        OWNER,
    )

    assert result == repository.job
    assert repository.job.status == "retry_wait"
    assert repository.failures[0]["error_code"] == "analysis_provider_rate_limited"
    assert repository.failures[0]["retryable"] is True
    assert repository.failures[0]["retry_at"] is not None
    assert loader.cleaned is True


@pytest.mark.asyncio
async def test_invalid_model_evidence_retries_with_attempt_limit(
    tmp_path: Path,
) -> None:
    repository = FakeRepository(running_job())
    loader = FakeLoader(tmp_path)
    invalid = valid_mapping()
    invalid["summary"] = {
        "text": "invented",
        "evidence_shot_ids": ["not-real"],
    }

    result = await execution(
        repository, loader, analyzer=FakeAnalyzer(invalid)
    ).execute(
        repository.job.id,
        repository.job.run_id,
        repository.job.run_no,
        OWNER,
    )

    assert result == repository.job
    assert repository.job.status == "retry_wait"
    assert repository.failures[0]["error_code"] == "invalid_model_output"
    assert repository.failures[0]["retryable"] is True
    assert loader.cleaned is True


@pytest.mark.asyncio
async def test_screenplay_never_falls_back_to_video_executor(tmp_path: Path) -> None:
    job = replace(
        running_job(),
        artifact_id=None,
        document_id=uuid4(),
        input_kind="screenplay",
        result_contract="screenplay-analysis",
    )
    repository = FakeRepository(job)
    loader = FakeLoader(tmp_path)

    result = await execution(
        repository, loader, analyzer=FakeAnalyzer(valid_mapping())
    ).execute(job.id, job.run_id, job.run_no, OWNER)

    assert result == repository.job
    assert repository.job.status == "failed"
    assert repository.failures[0]["error_code"] == "analysis_cli_unsupported"
    assert repository.heartbeats == []
    assert loader.cleaned is False


class CountingAnalyzer(FakeAnalyzer):
    def __init__(self, output: object) -> None:
        super().__init__(output)
        self.calls = 0

    async def analyze(self, request: VideoAnalysisRequest) -> object:
        self.calls += 1
        return await super().analyze(request)


@pytest.mark.asyncio
async def test_recorded_model_result_is_replayed_without_calling_provider(
    tmp_path: Path,
) -> None:
    repository = FakeRepository(running_job())
    first = CountingAnalyzer(valid_mapping())
    await execution(repository, FakeLoader(tmp_path), analyzer=first).execute(
        repository.job.id, repository.job.run_id, repository.job.run_no, OWNER
    )
    assert first.calls == 1
    assert repository.steps["video"][0] == "succeeded"

    # A replacement attempt of the same run (e.g. after publication was lost)
    # reuses the journaled payload instead of paying for a second call.
    repository.job = replace(repository.job, status="running", stage="preparing")
    replacement = CountingAnalyzer(valid_mapping())
    await execution(repository, FakeLoader(tmp_path), analyzer=replacement).execute(
        repository.job.id, repository.job.run_id, repository.job.run_no, "run:1:2"
    )

    assert replacement.calls == 0
    assert len(repository.published) == 2


@pytest.mark.asyncio
async def test_interrupted_model_call_fails_as_unknown_outcome_without_retrying(
    tmp_path: Path,
) -> None:
    repository = FakeRepository(running_job())
    # A previous attempt recorded the call as started and then disappeared.
    first = execution(repository, FakeLoader(tmp_path), analyzer=BlockingAnalyzer())
    repository.heartbeat_failure_stage = "analyzing"
    await first.execute(
        repository.job.id, repository.job.run_id, repository.job.run_no, OWNER
    )
    assert repository.steps["video"][0] == "started"

    repository.job = replace(repository.job, status="running", stage="preparing")
    repository.heartbeat_failure_stage = None
    analyzer = CountingAnalyzer(valid_mapping())
    await execution(repository, FakeLoader(tmp_path), analyzer=analyzer).execute(
        repository.job.id, repository.job.run_id, repository.job.run_no, "run:1:2"
    )

    assert analyzer.calls == 0
    assert repository.job.status == "failed"
    assert repository.failures[-1]["error_code"] == "analysis_outcome_unknown"
    assert repository.failures[-1]["retryable"] is False


@pytest.mark.asyncio
async def test_returned_provider_failure_releases_step_for_normal_retry(
    tmp_path: Path,
) -> None:
    repository = FakeRepository(running_job())
    await execution(
        repository,
        FakeLoader(tmp_path),
        analyzer=FakeAnalyzer(ProviderFailure("analysis_provider_rate_limited")),
    ).execute(repository.job.id, repository.job.run_id, repository.job.run_no, OWNER)

    assert repository.job.status == "retry_wait"
    assert "video" not in repository.steps


@pytest.mark.asyncio
async def test_timeout_preserves_started_call_and_never_auto_retries(
    tmp_path: Path,
) -> None:
    repository = FakeRepository(running_job())
    analyzer = CountingAnalyzer(TimeoutError())
    await execution(repository, FakeLoader(tmp_path), analyzer=analyzer).execute(
        repository.job.id, repository.job.run_id, repository.job.run_no, OWNER
    )
    assert analyzer.calls == 1
    assert repository.steps["video"][0] == "started"
    assert repository.job.status == "failed"
    assert repository.failures[-1]["error_code"] == "analysis_outcome_unknown"
    assert repository.failures[-1]["retryable"] is False


@pytest.mark.asyncio
async def test_received_invalid_output_is_saved_and_not_regenerated(
    tmp_path: Path,
) -> None:
    repository = FakeRepository(running_job())
    invalid = valid_mapping()
    invalid["summary"]["evidence_shot_ids"] = ["invented-shot"]
    first = CountingAnalyzer(invalid)
    await execution(repository, FakeLoader(tmp_path), analyzer=first).execute(
        repository.job.id, repository.job.run_id, repository.job.run_no, OWNER
    )
    assert first.calls == 1
    assert repository.steps["video"][0] == "succeeded"
    repository.job = replace(repository.job, status="running", stage="preparing")
    replacement = CountingAnalyzer(valid_mapping())
    await execution(repository, FakeLoader(tmp_path), analyzer=replacement).execute(
        repository.job.id, repository.job.run_id, repository.job.run_no, "run:1:2"
    )
    assert replacement.calls == 0
    assert len(repository.published) == 0


@pytest.mark.asyncio
async def test_explicit_known_invalid_response_is_recorded_without_reissue(
    tmp_path: Path,
) -> None:
    from app.integrations.ai_cli.errors import AnalysisCliError

    repository = FakeRepository(running_job())
    first = CountingAnalyzer(
        AnalysisCliError("invalid_model_output", outcome_known=True)
    )
    await execution(repository, FakeLoader(tmp_path), analyzer=first).execute(
        repository.job.id, repository.job.run_id, repository.job.run_no, OWNER
    )
    assert repository.steps["video"][0] == "failed"
    repository.job = replace(repository.job, status="running", stage="preparing")
    replacement = CountingAnalyzer(valid_mapping())
    await execution(repository, FakeLoader(tmp_path), analyzer=replacement).execute(
        repository.job.id, repository.job.run_id, repository.job.run_no, "run:1:2"
    )
    assert replacement.calls == 0
