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
    if result.media is None:
        lines.extend(
            (
                "## 整理后的正文"
                if result.language == "zh-CN"
                else "## Organized source text",
                "",
                "".join(section.body for section in result.sections),
                "",
            )
        )
        notes = [
            f"{section.heading} · Unicode "
            f"[{section.citations[0].start}, {section.citations[-1].end}): {item}"
            for section in result.sections
            for item in section.items
        ]
        if notes:
            lines.extend(
                (
                    "## 整理说明与待补项"
                    if result.language == "zh-CN"
                    else "## Organization notes and gaps",
                    "",
                )
            )
            lines.extend(f"- {markdown_text(item)}" for item in notes)
            lines.append("")
        citations = [item for section in result.sections for item in section.citations]
        if citations:
            lines.extend(
                (
                    "## 来源索引" if result.language == "zh-CN" else "## Source index",
                    "",
                    f"Unicode [{citations[0].start}, {citations[-1].end}) · "
                    "UTF-8 SHA256 "
                    f"`{citations[0].source_sha256}`",
                    "",
                )
            )
    else:
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
                lines.extend(
                    (
                        "**回看依据**"
                        if result.language == "zh-CN"
                        else "**Viewing evidence**",
                        "",
                    )
                )
                lines.extend(
                    f"- {format_range(item.start_ms, item.end_ms)}："
                    f"{markdown_text(item.note)}"
                    for item in section.evidence
                )
                lines.append("")
    if result.limitations:
        lines.extend(
            (
                "## 事实边界与待核验项"
                if result.language == "zh-CN"
                else "## Factual limits and verification needs",
                "",
            )
        )
        lines.extend(f"- {markdown_text(item)}" for item in result.limitations)
    return "\n".join(lines).rstrip() + "\n"
