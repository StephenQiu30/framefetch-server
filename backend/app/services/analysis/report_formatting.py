from __future__ import annotations

import html
import re

_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|])")


def markdown_text(value: str) -> str:
    normalized = " ".join(value.split())
    escaped_html = html.escape(normalized, quote=False)
    return _MARKDOWN_SPECIAL.sub(r"\\\1", escaped_html)


def markdown_block(value: str) -> str:
    return "\n\n".join(
        markdown_text(part) for part in value.splitlines() if part.strip()
    )


def format_time(milliseconds: int) -> str:
    total_seconds, millis = divmod(milliseconds, 1_000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def format_range(start_ms: int, end_ms: int) -> str:
    return f"{format_time(start_ms)}–{format_time(end_ms)}"


def format_shot_duration(start_ms: int, end_ms: int) -> str:
    return f"{(end_ms - start_ms) / 1_000:.1f}s"
