import hashlib
from dataclasses import replace

import pytest
from app.services.analysis.errors import (
    AnalysisApplicationError,
    AnalysisApplicationErrorCode,
)
from app.services.analysis.export_report import _read_verified
from app.services.analysis.models import AnalysisStoredReportFile
from app.services.analysis.report import render_analysis_report_markdown
from app.services.analysis.rules.result_items import Highlight, VisualAsset
from app.services.analysis.rules.result_models import AnalysisMedia
from app.services.analysis.rules.result_parser import parse_analysis_result
from app.services.analysis.rules.video_article_parser import parse_video_article_result
from app.services.analysis.screenplay_report import render_screenplay_report_markdown
from tests.unit.services.analysis.rules.screenplay_factories import (
    screenplay_analysis_result,
)
from tests.unit.workers.analysis.fixtures import valid_mapping


def report_result():
    payload = valid_mapping()
    payload["title"] = "产品 [演示](https://invalid.example)"
    payload["summary"] = {
        "text": "总结 <script>alert(1)</script> 与 **重点**。",
        "evidence_shot_ids": ["shot-a"],
    }
    result = parse_analysis_result(
        payload,
        AnalysisMedia(duration_ms=2_000, container="mp4", size_bytes=1_024),
        expected_language="zh-CN",
    )
    return replace(
        result,
        highlights=(
            Highlight(
                id="highlight-a",
                title="关键切换",
                description="展示主要界面。",
                score=92,
                reason="信息密度高。",
                start_ms=0,
                end_ms=2_000,
                evidence_shot_ids=("shot-a",),
            ),
        ),
        assets=(
            VisualAsset(
                id="asset-a",
                type="product",
                label="演示产品",
                description="画面中的产品界面。",
                first_seen_ms=0,
                evidence_shot_ids=("shot-a",),
            ),
        ),
    )


def test_markdown_report_is_complete_and_escapes_model_text() -> None:
    markdown = render_analysis_report_markdown(report_result())

    assert markdown.startswith("# 产品 \\[演示\\]\\(https://invalid\\.example\\)")
    headings = (
        "## 核心判断",
        "## 内容如何展开",
        "## 逐镜证据",
        "## 值得回看的片段",
        "## 修改建议",
        "## 需保持一致的视觉资产",
        "## 分析口径与局限",
    )
    assert all(heading in markdown for heading in headings)
    assert tuple(markdown.index(heading) for heading in headings) == tuple(
        sorted(markdown.index(heading) for heading in headings)
    )
    assert "**片长**：00:02.000 · **分析分镜**：1" in markdown
    assert "| 分镜 | 时间码 | 时长 | 画面内容 |" in markdown
    assert "| 分镜 001 | 00:00.000–00:02.000 | 2.0s |" in markdown
    assert "全景 / 固定 / 起始" in markdown
    assert "### 01｜开场建立" in markdown
    assert "**保留理由**：信息密度高。" in markdown
    assert "**类别**：产品 · **首次出现**：00:00.000" in markdown
    assert "## 一、基础信息" not in markdown
    assert "AI 制作建议" not in markdown
    assert "&lt;script&gt;alert\\(1\\)&lt;/script&gt;" in markdown
    assert "\\*\\*重点\\*\\*" in markdown
    assert markdown.endswith("\n")


def test_visual_report_uses_editorial_empty_states_without_padding() -> None:
    result = replace(report_result(), highlights=(), assets=())

    markdown = render_analysis_report_markdown(result)

    assert "报告不为了凑数放大普通片段" in markdown
    assert "暂不建立空泛目录" in markdown
    assert "未识别出独立视觉高光" not in markdown


def test_visual_report_keeps_the_editorial_structure_in_english() -> None:
    result = replace(report_result(), language="en-US")

    markdown = render_analysis_report_markdown(result)

    assert "## Key findings" in markdown
    assert "## How the video unfolds" in markdown
    assert "wide / static / none" in markdown
    assert "## Method and limits" in markdown


def test_screenplay_report_uses_coverage_sections_without_internal_ids() -> None:
    result = replace(
        screenplay_analysis_result(),
        title="剧本 [分析] <草稿>",
        synopsis="开端\n\n升级与选择。",
    )

    markdown = render_screenplay_report_markdown(result)

    assert markdown.startswith("# 剧本 \\[分析\\] &lt;草稿&gt;")
    assert "> 剧本审稿报告 · 共 1 场，已按原文顺序逐场审阅" in markdown
    assert "## 一、审稿结论" in markdown
    assert "输出语言" not in markdown
    assert "## 六、逐场附录" in markdown
    assert "### 第 1 场" in markdown
    assert "scene-1" not in markdown
    assert "### 优先修改" in markdown
    assert "> 本项没有独立发现。" in markdown
    assert "## 七、阅读说明" in markdown
    assert "分析判断仍需对照原文核查" in markdown
    assert "开端\n\n升级与选择。" in markdown
    assert markdown.endswith("\n")


def test_screenplay_report_keeps_finding_paragraphs_and_english_labels() -> None:
    base = screenplay_analysis_result()
    finding = replace(
        base.structure.acts[0],
        title="Motive fades in act two",
        description="The key appears late.\nThe search lacks a reason.",
    )
    result = replace(base, language="en-US", priority_revisions=(finding,))

    markdown = render_screenplay_report_markdown(result)

    assert "## 1. Key findings" in markdown
    assert "**1\\. Motive fades in act two**" in markdown
    assert "The key appears late\\.\n\nThe search lacks a reason\\." in markdown
    assert "## 6. Scene-by-scene notes" in markdown
    assert "审稿" not in markdown


def test_video_article_report_is_complete_copy_without_review_metadata() -> None:
    result = parse_video_article_result(
        {
            "language": "zh-CN",
            "title": "问题如何变成方法",
            "lead": "视频用一个具体问题引出一套可复用的方法。",
            "sections": [
                {
                    "id": "section-1",
                    "title": "从问题开始",
                    "body": "先把问题说清楚，再决定下一步。",
                    "evidence": [
                        {"start_ms": 0, "end_ms": 2_000, "note": "开场问题场景。"}
                    ],
                }
            ],
            "key_points": ["先定义问题，再选择方法。"],
            "closing": "方法的价值在于可以被复用。",
            "limitations": ["编辑回查备注：未提供长期测试记录。"],
        },
        AnalysisMedia(duration_ms=2_000, container="mp4", size_bytes=1_024),
        expected_language="zh-CN",
    )

    markdown = render_analysis_report_markdown(result)

    assert markdown.startswith("# 问题如何变成方法\n\n视频用一个具体问题")
    assert "## 从问题开始" in markdown
    assert "先把问题说清楚，再决定下一步。" in markdown
    assert markdown.endswith("方法的价值在于可以被复用。\n")
    for metadata in (
        "00:00.000–00:02.000",
        "开场问题场景。",
        "先定义问题，再选择方法。",
        "编辑回查备注",
        "编辑摘要",
        "编辑附录",
    ):
        assert metadata not in markdown
    assert result.sections[0].evidence[0].start_ms == 0
    assert result.key_points == ("先定义问题，再选择方法。",)
    assert result.limitations == ("编辑回查备注：未提供长期测试记录。",)


class ObjectReader:
    def __init__(self, content: bytes | Exception) -> None:
        self.content = content

    async def read(self, object_key: str) -> bytes:
        if isinstance(self.content, Exception):
            raise self.content
        return self.content


@pytest.mark.asyncio
async def test_stored_report_download_verifies_size_and_sha256() -> None:
    content = b"# verified report\n"
    stored = AnalysisStoredReportFile(
        object_key="private/report.md",
        media_type="text/markdown; charset=utf-8",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )

    assert await _read_verified(ObjectReader(content), stored) == content
    for reader in (ObjectReader(b"corrupt"), ObjectReader(FileNotFoundError())):
        with pytest.raises(AnalysisApplicationError) as caught:
            await _read_verified(reader, stored)
        assert caught.value.code is AnalysisApplicationErrorCode.REPORT_UNAVAILABLE
