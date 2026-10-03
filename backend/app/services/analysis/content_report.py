"""Render reader content only; evidence and editorial records stay separate."""

from app.services.analysis.report_formatting import markdown_text
from app.services.analysis.rules.content_document import ContentDraft


def render_content_markdown(result: ContentDraft) -> str:
    lines: list[str] = []
    if result.title:
        lines.extend((f"# {markdown_text(result.title)}", ""))
    for block in result.blocks:
        if block.type == "heading":
            lines.append(f"{'#' * block.level} {markdown_text(block.text)}")
        elif block.type == "list":
            for index, item in enumerate(block.items, 1):
                prefix = f"{index}." if block.ordered else "-"
                lines.append(f"{prefix} {markdown_text(item)}")
        elif block.type == "quote":
            lines.extend(f"> {markdown_text(line)}" for line in block.text.splitlines())
        else:
            lines.extend(markdown_text(line) for line in block.text.splitlines())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
