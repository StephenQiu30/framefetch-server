from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services.analysis.report_formatting import markdown_block as _markdown_block
from app.services.analysis.report_formatting import markdown_text as _markdown_text
from app.services.analysis.rules.contracts import contract_for_result
from app.services.analysis.rules.enums import AnalysisResultKind
from app.services.analysis.rules.result_models import VideoArticleResult
from app.services.analysis.rules.result_types import AnalysisResult
from app.services.analysis.screenplay_report import render_screenplay_report_markdown
from app.services.analysis.structured_report import render_structured_report_markdown
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
    for section in result.sections:
        lines.extend(
            (
                f"## {_markdown_text(section.title)}",
                "",
                _markdown_block(section.body),
                "",
            )
        )
    lines.extend((_markdown_block(result.closing), ""))
    return "\n".join(lines).rstrip() + "\n"


_RENDERERS: dict[AnalysisResultKind, Callable[[Any], str]] = {
    AnalysisResultKind.VIDEO_VISUAL_ANALYSIS: render_video_analysis_report_markdown,
    AnalysisResultKind.VIDEO_ARTICLE: _render_video_article_report_markdown,
    AnalysisResultKind.SCREENPLAY_ANALYSIS: render_screenplay_report_markdown,
    AnalysisResultKind.SCREENPLAY_REWRITE: render_screenplay_report_markdown,
    AnalysisResultKind.STRUCTURED_REPORT: render_structured_report_markdown,
}
