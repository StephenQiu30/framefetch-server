from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from app.integrations.analysis_skill_catalog import BuiltinAnalysisSkillCatalog
from app.services.analysis.report import render_analysis_report_markdown
from app.services.analysis.rules.enums import AnalysisInputKind, AnalysisResultContract
from app.services.analysis.rules.errors import AnalysisValidationError
from app.services.analysis.rules.result_models import AnalysisMedia
from app.services.analysis_execution.errors import AnalysisOutcomeUnknown
from app.services.analysis_execution.models import VideoAnalysisRequest
from app.services.analysis_execution.monitor import AnalysisLeaseMonitor
from app.services.analysis_execution.ports import AnalyzerSelection
from app.services.analysis_execution.video_editorial import execute_video_editorial
from tests.unit.services.analysis.rules.test_video_article import article_payload

from .fakes import NOW, running_job
from .test_content_execution import ContentRepository, review


def plan():
    return {
        "reader_question": "读者关心什么",
        "angle": "从结果展开",
        "movement": ["具体细节", "判断"],
        "omit": ["无关参数"],
        "revisit_ms": [1000],
    }


class Analyzer:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.requests = []

    async def analyze(self, request):
        self.requests.append(request)
        value = next(self.outputs)
        if isinstance(value, Exception):
            raise value
        return value


def setup(tmp_path, outputs):
    skill = BuiltinAnalysisSkillCatalog().resolve(
        "video-to-article", AnalysisInputKind.VIDEO
    )
    job = replace(
        running_job(),
        skill_id="video-to-article",
        result_contract="video-article",
        skill_instructions=skill.instructions,
        skill_instructions_sha256=skill.instructions_sha256,
    )
    repository = ContentRepository(job)
    monitor = AnalysisLeaseMonitor(
        repository=repository,
        job_id=job.id,
        run_id=job.run_id,
        owner=job.lease_owner,
        attempt=job.attempt,
        clock=lambda: NOW,
        lease_for=timedelta(seconds=30),
        interval=0.01,
    )
    analyzer = Analyzer(outputs)
    request = VideoAnalysisRequest(
        artifact=tmp_path / "video.bin",
        workspace=tmp_path,
        duration_ms=3000,
        size_bytes=1024,
        container="mp4",
        output_language="zh-CN",
        skill_id="video-to-article",
        skill_instructions=skill.instructions,
        result_contract=AnalysisResultContract.VIDEO_ARTICLE,
    )
    selection = AnalyzerSelection(
        analyzer, "controlled", "controlled", "controlled", "a" * 64
    )
    media = AnalysisMedia(duration_ms=3000, size_bytes=1024, container="mp4")

    async def execute():
        return await execute_video_editorial(job, request, selection, monitor, media)

    return analyzer, repository, execute


def finding():
    result = review(True)
    result["findings"][0]["block_id"] = "section-001"
    return result


@pytest.mark.asyncio
async def test_article_can_be_only_paragraphs_and_replays_three_calls(tmp_path: Path):
    payload = article_payload()
    payload.update(lead="", closing="", key_points=[])
    for section in payload["sections"]:
        section["title"] = ""
    analyzer, repository, execute = setup(tmp_path, [plan(), payload, review()])
    result = await execute()
    assert result.review_status == "passed"
    assert [item.stage for item in analyzer.requests] == ["plan", "draft", "review"]
    assert analyzer.requests[1].observation_ms == (1000,)
    assert "# Review" not in analyzer.requests[1].stage_prompt
    assert "# Draft" not in analyzer.requests[2].stage_prompt
    assert repository.binding["max_model_calls"] == 5
    assert await execute() == result
    assert len(analyzer.requests) == 3
    markdown = render_analysis_report_markdown(result)
    assert "\n## " not in markdown
    assert "reader_question" not in markdown and "limitations" not in markdown


@pytest.mark.asyncio
async def test_video_revision_targets_only_flagged_section_and_stops_at_five(tmp_path):
    revised = deepcopy(article_payload())
    revised["sections"][1]["body"] = "修订后的这一段。"
    analyzer, _, execute = setup(
        tmp_path, [plan(), article_payload(), finding(), revised, finding()]
    )
    result = await execute()
    assert result.review_status == "needs_review"
    assert len(result.review_history) == 2
    assert len(analyzer.requests) == 5
    assert result.sections[0].body == article_payload()["sections"][0]["body"]


@pytest.mark.asyncio
async def test_video_revision_cannot_change_unselected_title(tmp_path):
    revised = deepcopy(article_payload())
    revised["title"] = "未经要求重写整篇"
    analyzer, _, execute = setup(
        tmp_path, [plan(), article_payload(), finding(), revised]
    )
    with pytest.raises(AnalysisValidationError):
        await execute()
    assert len(analyzer.requests) == 4


@pytest.mark.asyncio
async def test_invalid_observation_plan_stays_a_paid_result_on_replay(tmp_path):
    invalid = plan()
    invalid["revisit_ms"] = [3000]
    analyzer, _, execute = setup(tmp_path, [invalid])
    for _ in range(2):
        with pytest.raises(AnalysisValidationError):
            await execute()
    assert len(analyzer.requests) == 1


@pytest.mark.asyncio
async def test_unknown_video_review_is_not_reissued(tmp_path):
    analyzer, _, execute = setup(
        tmp_path, [plan(), article_payload(), RuntimeError("interrupted")]
    )
    for _ in range(2):
        with pytest.raises(AnalysisOutcomeUnknown):
            await execute()
    assert len(analyzer.requests) == 3
