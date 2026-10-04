"""The original video methods use a finite plan, draft and independent review."""

import json
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from app.integrations.analysis_skill_catalog import BuiltinAnalysisSkillCatalog
from app.services.analysis.rules.enums import AnalysisInputKind, AnalysisResultContract
from app.services.analysis.rules.errors import AnalysisValidationError
from app.services.analysis.rules.result_models import AnalysisMedia
from app.services.analysis_execution.errors import AnalysisOutcomeUnknown
from app.services.analysis_execution.models import VideoAnalysisRequest
from app.services.analysis_execution.monitor import AnalysisLeaseMonitor
from app.services.analysis_execution.ports import AnalyzerSelection
from app.services.analysis_execution.video_editorial import execute_video_editorial
from tests.unit.workers.analysis.fakes import NOW, FakeRepository, running_job


@pytest.mark.parametrize(
    "outcome",
    ["passed", "revision", "coverage_revision", "unknown", "invalid_location"],
)
async def test_original_video_plan_is_three_calls_or_one_bounded_revision(
    tmp_path, outcome
):
    skill = BuiltinAnalysisSkillCatalog().resolve(
        "video-review", AnalysisInputKind.VIDEO
    )
    job = replace(
        running_job(),
        skill_id="video-review",
        skill_instructions=skill.instructions,
        skill_instructions_sha256=skill.instructions_sha256,
        result_contract="structured-report",
    )
    repository = FakeRepository(job)
    repository.bind_execution = AsyncMock()
    monitor = AnalysisLeaseMonitor(
        repository=repository,
        job_id=job.id,
        run_id=job.run_id,
        owner="worker",
        attempt=1,
        clock=lambda: NOW,
        lease_for=timedelta(seconds=60),
        interval=1,
        execution_deadline=NOW + timedelta(seconds=900),
    )
    plan = {
        "reader_question": "硬切处发生什么变化？",
        "angle": "只描述已观察到的画面",
        "movement": ["先交代观察范围，再指出变化"],
        "omit": ["未知声音内容"],
        "revisit_ms": [500, 1500],
    }
    draft = {
        "language": "zh-CN",
        "title": "画面分析",
        "summary": "只依据已观察画面描述变化。",
        "sections": [
            {
                "id": "cut",
                "heading": "切点",
                "body": "约一秒处画面变化，实际精确切点仍待核查。",
                "items": [],
                "evidence": [{"start_ms": 500, "end_ms": 1501, "note": "相邻画面回看"}],
            }
        ],
        "limitations": ["未核验声音"],
    }
    passed = {"needs_material": False, "findings": []}
    revision = {
        "needs_material": False,
        "findings": [
            {
                "block_id": "section-000",
                "severity": "major",
                "category": "expression",
                "problem": "区分候选切点和已核精确切点。",
                "correction": "保留候选范围说明。",
            }
        ],
    }
    needs_revision = outcome in {"revision", "coverage_revision"}
    if outcome == "coverage_revision":
        revision["findings"][0]["block_id"] = "limitations"
    values = [plan, draft, revision if needs_revision else passed]
    if needs_revision:
        values += [
            {**draft, "limitations": ["未逐帧检查，未核验声音"]}
            if outcome == "coverage_revision"
            else draft,
            passed,
        ]
    if outcome == "unknown":
        values[1] = TimeoutError("unknown execution")
    if outcome == "invalid_location":
        values[2] = {
            "needs_material": False,
            "findings": [{**revision["findings"][0], "block_id": "cut"}],
        }
    analyzer = AsyncMock()
    analyzer.analyze.side_effect = values
    selection = AnalyzerSelection(analyzer, "controlled", "controlled", "controlled")
    request = VideoAnalysisRequest(
        tmp_path / "video.bin",
        tmp_path,
        2000,
        100,
        "mp4",
        "zh-CN",
        "video-review",
        skill.instructions,
        AnalysisResultContract.STRUCTURED_REPORT,
    )
    if outcome == "unknown":
        with pytest.raises(AnalysisOutcomeUnknown):
            await execute_video_editorial(
                job,
                request,
                selection,
                monitor,
                AnalysisMedia(duration_ms=2000, container="mp4", size_bytes=100),
            )
        assert analyzer.analyze.await_count == 2
        assert repository.steps["draft"][0] == "started"
    elif outcome == "invalid_location":
        with pytest.raises(AnalysisValidationError):
            await execute_video_editorial(
                job,
                request,
                selection,
                monitor,
                AnalysisMedia(duration_ms=2000, container="mp4", size_bytes=100),
            )
        assert analyzer.analyze.await_count == 3
        assert repository.steps["review"][0] == "succeeded"
    else:
        result = await execute_video_editorial(
            job,
            request,
            selection,
            monitor,
            AnalysisMedia(duration_ms=2000, container="mp4", size_bytes=100),
        )
        assert analyzer.analyze.await_count == (5 if needs_revision else 3)
        assert result.review_status == "passed"
        assert [call.args[0].stage for call in analyzer.analyze.await_args_list] == (
            ["plan", "draft", "review", "revise-01", "verify-01"]
            if needs_revision
            else ["plan", "draft", "review"]
        )
    assert repository.bind_execution.call_args.args[1]["max_model_calls"] == 5
    for call in analyzer.analyze.await_args_list:
        value = call.args[0]
        if value.stage in {"review", "verify-01"}:
            schema = json.loads(value.schema_json)
            assert schema["$defs"]["ContentFinding"]["properties"]["block_id"][
                "enum"
            ] == ["limitations", "section-000", "summary", "title"]
            assert "不能使用该映射的值" in value.stage_prompt
    bound_schema = repository.bind_execution.call_args.args[1]["schemas"]["review"]
    assert (
        "enum" not in bound_schema["$defs"]["ContentFinding"]["properties"]["block_id"]
    )
    assert repository.bind_execution.call_args.kwargs["deadline"] == NOW + timedelta(
        seconds=900
    )
