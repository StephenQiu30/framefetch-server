"""Product calibration examples exercise actual contracts, not model quality."""

import json
from pathlib import Path

import pytest
from app.services.analysis.report import render_analysis_report_markdown
from app.services.analysis.rules.errors import AnalysisValidationError
from app.services.analysis.rules.result_models import AnalysisMedia
from app.services.analysis.rules.result_parser import parse_analysis_result
from app.services.analysis.rules.result_types import AnalysisResult
from app.services.analysis.rules.screenplay_parser import (
    parse_screenplay_analysis_result,
)
from app.services.analysis.rules.video_article_parser import parse_video_article_result

_EXAMPLES = Path(__file__).with_name("examples")


def _read(name: str) -> dict:
    return json.loads((_EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def _parse(name: str, payload: dict) -> AnalysisResult:
    sources = _read("source-cases")
    if name == "screenplay-analysis":
        return parse_screenplay_analysis_result(
            payload,
            expected_language="zh-CN",
            source_scene_ids=tuple(sources["screenplay"]["source_scene_ids"]),
        )
    video = sources["video"]
    media = AnalysisMedia(
        duration_ms=video["duration_ms"],
        container=video["container"],
        size_bytes=video["size_bytes"],
    )
    if name == "video-article":
        return parse_video_article_result(payload, media, expected_language="zh-CN")
    return parse_analysis_result(payload, media, expected_language="zh-CN")


@pytest.mark.parametrize(
    "name", ["comprehensive", "video-article", "screenplay-analysis"]
)
def test_editorial_examples_parse_and_render_with_source_boundaries(name: str) -> None:
    payload = _read(name)
    result = _parse(name, payload)
    markdown = render_analysis_report_markdown(result)

    assert markdown.startswith(f"# {payload['title']}\n")
    assert markdown.endswith("\n")
    if name == "screenplay-analysis":
        assert "第 1 场" in markdown and "第 2 场" in markdown
        assert "尚未呈现结果" in markdown
        assert "scene-opening" not in markdown
    else:
        assert "长期不漏水" in markdown or "长时间携带" in markdown
        assert "00:07.000–00:10.000" in markdown
        if name == "video-article":
            appendix = markdown.index("## 编辑附录")
            assert "还需要更完整的测试" in markdown[:appendix]
            assert "00:07.000" not in markdown[:appendix]


def test_comprehensive_example_rejects_an_unobserved_shot_reference() -> None:
    payload = _read("comprehensive")
    payload["summary"]["evidence_shot_ids"] = ["shot-not-in-source"]

    with pytest.raises(AnalysisValidationError):
        _parse("comprehensive", payload)


def test_article_example_rejects_evidence_outside_source_duration() -> None:
    payload = _read("video-article")
    payload["sections"][0]["evidence"][0]["end_ms"] = 12001

    with pytest.raises(AnalysisValidationError):
        _parse("video-article", payload)


def test_screenplay_example_rejects_reordered_source_scenes() -> None:
    payload = _read("screenplay-analysis")
    payload["scenes"].reverse()

    with pytest.raises(AnalysisValidationError):
        _parse("screenplay-analysis", payload)
