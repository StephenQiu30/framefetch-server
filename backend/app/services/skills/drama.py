"""Deterministic chapter/scene locators for evidence-based drama analysis."""

from __future__ import annotations

import hashlib
import re


def index_drama_source(text: str) -> dict[str, object]:
    if not text.strip() or len(text) > 2_000_000:
        raise ValueError("drama material needs 1 to 2000000 Unicode characters")
    headings = list(
        re.finditer(
            r"(?m)^[^\S\n]*(?:第[^\S\n]*[〇零一二三四五六七八九十百千万两\d]+[^\S\n]*(?P<unit>[章回节场])[^\n]{0,70}"
            r"|(?P<chapter>Chapter)[^\S\n]+(?:[1-9]\d*|[IVXLCDM]+)\b[^\n]{0,70}"
            r"|(?:INT\.|EXT\.|INT/EXT\.|内景|外景)[^\n]{0,70})$",
            text,
            re.IGNORECASE,
        )
    )
    counts = {
        unit: sum(
            ("chapter" if match.group("chapter") else match.group("unit")) == unit
            for match in headings
        )
        for unit in ("章", "回", "节", "场", "chapter")
    }
    dominant = (
        max(counts, key=lambda key: counts[key]) if any(counts.values()) else None
    )
    if dominant is not None:
        headings = [
            match
            for match in headings
            if dominant
            == ("chapter" if match.group("chapter") else match.group("unit"))
        ]
    boundaries = [(match.start(), match.group(0)) for match in headings]
    if not boundaries:
        boundaries = [(0, "完整输入")]
    elif boundaries[0][0] != 0:
        boundaries.insert(0, (0, "前置文本"))
    parts: list[dict[str, object]] = []
    for index, (start, title) in enumerate(boundaries):
        end = boundaries[index + 1][0] if index + 1 < len(boundaries) else len(text)
        parts.append(
            {
                "id": f"unit-{index + 1}",
                "sequence": index + 1,
                "title": title,
                "start": start,
                "end": end,
                "sha256": hashlib.sha256(text[start:end].encode()).hexdigest(),
                "sha256_scope": "utf8_text_slice",
            }
        )
    return {
        "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "source_sha256_scope": "utf8_text",
        "offset_unit": "unicode_codepoints",
        "chapter_unit": dominant,
        "units": parts,
        "coverage_ratio": 1.0,
        "sampled": False,
        "limitations": ["索引不判定戏剧功能；无标题文本按完整输入分析。"],
    }
