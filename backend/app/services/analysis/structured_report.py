from __future__ import annotations

from app.services.analysis.report_formatting import (
    format_range,
    markdown_block,
    markdown_text,
)
from app.services.analysis.rules.structured_report import StructuredReportResult


def render_structured_report_markdown(result: StructuredReportResult) -> str:
    """Render a generic report; every model string is escaped as plain text."""
    lines = [f"# {markdown_text(result.title)}", "", markdown_block(result.summary), ""]
    for index, section in enumerate(result.sections, start=1):
        lines.extend(
            (
                f"## {index}. {markdown_text(section.heading)}",
                "",
                markdown_block(section.body),
                "",
            )
        )
        if section.items:
            lines.extend(f"- {markdown_text(item)}" for item in section.items)
            lines.append("")
        if section.evidence:
            lines.extend(("画面证据：", ""))
            lines.extend(
                f"- {format_range(item.start_ms, item.end_ms)}："
                f"{markdown_text(item.note)}"
                for item in section.evidence
            )
            lines.append("")
    if result.limitations:
        lines.extend(("## 事实边界与待核验项", ""))
        lines.extend(f"- {markdown_text(item)}" for item in result.limitations)
    return "\n".join(lines).rstrip() + "\n"
