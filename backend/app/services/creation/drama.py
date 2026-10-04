"""Deterministic chapter/scene locators for evidence-based drama analysis."""

from __future__ import annotations

import hashlib
import re


def index_drama_source(text: str) -> dict[str, object]:
    if not text.strip() or len(text) > 30000:
        raise ValueError("drama material needs 1 to 30000 Unicode characters")
    headings = list(
        re.finditer(
            r"(?m)^\s*(?:第\s*[〇零一二三四五六七八九十百千万两\d]+\s*(?P<unit>[章回节场])[^\n]{0,70}"
            r"|(?:INT\.|EXT\.|INT/EXT\.|内景|外景)[^\n]{0,70})$",
            text,
        )
    )
    counts = {
        unit: sum(match.group("unit") == unit for match in headings)
        for unit in "章回节场"
    }
    dominant = (
        max(counts, key=lambda key: counts[key]) if any(counts.values()) else None
    )
    if dominant is not None:
        headings = [match for match in headings if dominant == match.group("unit")]
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


DRAMA_ANALYSIS_METHOD = """
剧情分析关注人物想要什么、阻力、行动因果、信息变化、转折、代价和结果。
按已固定章节/场景索引逐单元提炼戏剧功能，分别组织人物与别名候选、关系、
剧情单元、伏笔与兑现、节奏情绪、世界规则和改编风险。别名须有同指证据。
结构化结果只使用 sections、characters、findings、unresolved 四个字段。
sections 分别收录各已固定单元的剧情功能、关系、伏笔兑现、节奏与世界规则；
每个固定单元必须有一项 sections，其 id 为 material_id/unit-N，明确其实际分析及不足；
characters 收录别名与目标变化；findings 收录问题、影响与建议。每项绑定证据序号。
有选择范围就报告实际覆盖率，抽样结论不能写成全量；跳过项逐项记录。
只分析原著/剧本，不写新剧本、分镜、资产、生成媒体或剪辑，不替作者确定改编契约。
不强制题材公式、反转数量或章数比例；专业建议不能伪装成机器可证明的事实。
""".strip()
