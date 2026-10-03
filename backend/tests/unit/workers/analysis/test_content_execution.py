from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from app.integrations.ai_cli.errors import AnalysisCliError
from app.integrations.analysis_skill_catalog import BuiltinAnalysisSkillCatalog
from app.services.analysis.rules.content_document import (
    ContentDocumentResult,
    ContentSourceSet,
)
from app.services.analysis.rules.enums import AnalysisInputKind
from app.services.analysis.rules.errors import AnalysisValidationError
from app.services.analysis_execution.content_executor import ContentExecutor
from app.services.analysis_execution.content_models import ContentModelRequest
from app.services.analysis_execution.errors import (
    AnalysisExecutionError,
    AnalysisOutcomeUnknown,
)
from app.services.analysis_execution.monitor import AnalysisLeaseMonitor
from app.services.analysis_execution.ports import AnalyzerSelection

from .fakes import NOW, FakeRepository, running_job


def source(document_type="article"):
    return ContentSourceSet.model_validate(
        {
            "materials": [
                {
                    "id": "notes",
                    "title": "试用笔记",
                    "text": (
                        "旋紧杯盖后，杯子短暂倒置，桌面未见水滴。未做长时间携带测试。"
                    ),
                }
            ],
            "brief": {"document_type": document_type, "purpose": "介绍这次观察"},
        }
    )


def draft(document_type="article"):
    return {
        "document_type": document_type,
        "language": "zh-CN",
        "title": None if document_type == "post" else "旋紧杯盖之后",
        "blocks": [
            {
                "id": "opening",
                "type": "paragraph",
                "text": "杯盖旋紧后，杯子短暂倒置，桌面上没有看到水滴。",
            },
            {
                "id": "closing",
                "type": "paragraph",
                "text": "这次只看了短暂倒置，长时间携带还没有测试。",
            },
        ],
        "evidence_index": [
            {
                "block_id": "opening",
                "material_id": "notes",
                "segment_id": "segment-000",
                "quote": "桌面未见水滴",
            }
        ],
    }


def review(major=False, needs_material=False):
    return {
        "needs_material": needs_material,
        "findings": [
            {
                "block_id": "closing",
                "severity": "major",
                "category": "missing_material" if needs_material else "expression",
                "problem": "结尾可更自然",
                "correction": "收窄到这次观察",
            }
        ]
        if major or needs_material
        else [],
    }


class ContentRepository(FakeRepository):
    binding: dict[str, object] | None = None

    async def bind_execution(
        self,
        run_id,
        binding,
        *,
        owner: str,
        attempt: int,
        now: datetime,
        deadline: datetime,
    ):
        assert owner == self.job.lease_owner and attempt == self.job.attempt
        assert deadline > now
        if self.binding is not None and self.binding != binding:
            raise AnalysisExecutionError("analysis_configuration_changed")
        self.binding = binding


class Analyzer:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.requests = []

    async def generate_content(self, request: ContentModelRequest):
        self.requests.append(request)
        value = next(self.outputs)
        if isinstance(value, Exception):
            raise value
        return value


class Resolver:
    def __init__(self, analyzer):
        self.analyzer = analyzer

    async def resolve(self):
        return AnalyzerSelection(
            self.analyzer, "controlled", "controlled", "controlled", "a" * 64
        )


def setup(tmp_path, outputs, document_type="article"):
    materials = source(document_type)
    catalog = BuiltinAnalysisSkillCatalog()
    skill = catalog.resolve(f"content-{document_type}", AnalysisInputKind.CONTENT)
    assert skill is not None
    job = replace(
        running_job(),
        artifact_id=None,
        input_kind="content",
        result_contract="content-document",
        content_source=materials,
        input_sha256=materials.sha256,
        skill_instructions=skill.instructions,
        skill_instructions_sha256=skill.instructions_sha256,
    )
    repository = ContentRepository(job)
    analyzer = Analyzer(outputs)
    executor = ContentExecutor(resolver=Resolver(analyzer), workspace_root=tmp_path)
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
    return job, repository, analyzer, executor, monitor


@pytest.mark.asyncio
@pytest.mark.parametrize("document_type", ["article", "post", "guide"])
async def test_two_calls_publish_clean_body_and_replay_without_call(
    tmp_path, document_type
):
    job, repository, analyzer, executor, monitor = setup(
        tmp_path, [draft(document_type), review()], document_type
    )
    output = await executor.execute(job, monitor)
    assert isinstance(output.result, ContentDocumentResult)
    assert output.result.review_status == "passed"
    assert [request.stage for request in analyzer.requests] == ["draft", "review"]
    assert "# Review" not in analyzer.requests[0].prompt
    assert "# Draft" not in analyzer.requests[1].prompt
    assert list(tmp_path.iterdir()) == []
    replay = await executor.execute(job, monitor)
    assert replay == output
    assert len(analyzer.requests) == 2
    assert repository.binding["max_model_calls"] == 4


@pytest.mark.asyncio
async def test_revision_keeps_untargeted_blocks_and_stops_after_four_calls(tmp_path):
    revised = draft()
    revised["blocks"][1]["text"] = "这次观察只覆盖短暂倒置。"
    job, _, analyzer, executor, monitor = setup(
        tmp_path, [draft(), review(True), revised, review(True)]
    )
    output = await executor.execute(job, monitor)
    assert output.result.review_status == "needs_review"
    assert len(analyzer.requests) == 4
    assert output.result.blocks[0].text == draft()["blocks"][0]["text"]


@pytest.mark.asyncio
async def test_revision_cannot_rewrite_untargeted_opening(tmp_path):
    changed = draft()
    changed["blocks"][0]["text"] = "改写整篇开头"
    job, _, analyzer, executor, monitor = setup(
        tmp_path, [draft(), review(True), changed]
    )
    with pytest.raises(AnalysisValidationError):
        await executor.execute(job, monitor)
    assert len(analyzer.requests) == 3


@pytest.mark.asyncio
async def test_missing_material_retains_actionable_review_without_regeneration(
    tmp_path,
):
    job, _, analyzer, executor, monitor = setup(
        tmp_path, [draft(), review(needs_material=True)]
    )
    output = await executor.execute(job, monitor)
    assert output.result.review_status == "needs_material"
    assert output.result.review_history[-1].findings[0].correction
    assert len(analyzer.requests) == 2


@pytest.mark.asyncio
async def test_unknown_call_is_not_reissued(tmp_path):
    job, _, analyzer, executor, monitor = setup(
        tmp_path, [AnalysisCliError("analysis_cli_timeout")]
    )
    for _ in range(2):
        with pytest.raises(AnalysisOutcomeUnknown):
            await executor.execute(job, monitor)
    assert len(analyzer.requests) == 1
    assert list(tmp_path.iterdir()) == []
