from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services.analysis.report_formatting import format_range as _format_range
from app.services.analysis.report_formatting import markdown_block as _markdown_block
from app.services.analysis.report_formatting import markdown_text as _markdown_text
from app.services.analysis.rules.contracts import contract_for_result
from app.services.analysis.rules.enums import AnalysisResultKind
from app.services.analysis.rules.result_models import VideoArticleResult
from app.services.analysis.rules.result_types import AnalysisResult
from app.services.analysis.screenplay_report import render_screenplay_report_markdown
from app.services.analysis.video_report import render_video_analysis_report_markdown


def render_analysis_report_markdown(result: AnalysisResult) -> str:
    renderer = _RENDERERS[contract_for_result(result).kind]
    return renderer(result)


def _render_video_article_report_markdown(result: VideoArticleResult) -> str:
    lines = [
        f"# {_markdown_text(result.title)}",
        "",
        _markdown_block(result.lead),
        "",
    ]
    for index, section in enumerate(result.sections, start=1):
        lines.extend(
            (
                f"## {index}. {_markdown_text(section.title)}",
                "",
                _markdown_block(section.body),
                "",
            )
        )
    lines.extend((_markdown_block(result.closing), "", "---", ""))
    lines.extend(("## 编辑摘要（发布前可选）", ""))
    lines.extend(f"- {_markdown_text(item)}" for item in result.key_points)
    lines.extend(
        (
            "",
            "## 编辑附录：视频证据（发布前可删除）",
            "",
            "> 以下时间码仅用于编辑回看原视频，不代表独立的外部事实核验。",
            "",
        )
    )
    for index, section in enumerate(result.sections, start=1):
        lines.extend((f"### {index}. {_markdown_text(section.title)}", ""))
        lines.extend(
            (
                f"- {_format_range(item.start_ms, item.end_ms)}："
                f"{_markdown_text(item.note)}"
            )
            for item in section.evidence
        )
        lines.append("")
    if result.limitations:
        lines.extend(("### 事实边界与待核验项", ""))
        lines.extend(f"- {_markdown_text(item)}" for item in result.limitations)
    return "\n".join(lines).rstrip() + "\n"


_RENDERERS: dict[AnalysisResultKind, Callable[[Any], str]] = {
    AnalysisResultKind.VIDEO_VISUAL_ANALYSIS: render_video_analysis_report_markdown,
    AnalysisResultKind.VIDEO_ARTICLE: _render_video_article_report_markdown,
    AnalysisResultKind.SCREENPLAY_ANALYSIS: render_screenplay_report_markdown,
    AnalysisResultKind.SCREENPLAY_REWRITE: render_screenplay_report_markdown,
}
