from __future__ import annotations

import html
import re

from app.services.analysis.rules.screenplay_result_items import ScreenplayFinding
from app.services.analysis.rules.screenplay_results import (
    ScreenplayAnalysisResult,
    ScreenplayRewriteResult,
)

_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+.!|])")

_ZH = {
    "deck": (
        "剧本审稿报告 · 共 {scenes} 场，已按原文顺序逐场审阅 · 主要人物 {characters} 个"
    ),
    "conclusions": "一、审稿结论",
    "revisions": "优先修改",
    "no_revisions": "本次审稿没有提出有充分文本依据的优先修改项。",
    "strengths": "值得保留",
    "no_strengths": "本次审稿没有单列文本优势。",
    "overview": "二、故事概览",
    "logline": "一句话梗概",
    "synopsis": "故事梗概",
    "structure": "三、结构与节奏",
    "acts": "段落结构",
    "turning_points": "关键转折",
    "pacing": "节奏判断",
    "characters": "四、人物",
    "no_characters": "本次结果没有单列的主要人物。",
    "goal": "目标",
    "conflict": "阻力",
    "arc": "变化",
    "dialogue": "五、对白",
    "dialogue_findings": "对白发现",
    "appendix": "六、逐场附录",
    "appendix_intro": "以下按原文顺序列出每一场的审阅要点，供修改时对照原稿。",
    "scene": "第 {index} 场",
    "purpose": "功能",
    "scene_conflict": "冲突",
    "turn": "转变",
    "scene_pacing": "节奏",
    "no_scene_findings": "本场没有独立发现。",
    "empty": "本项没有独立发现。",
    "notes": "七、阅读说明",
    "notes_body": (
        "场次按上传剧本的规范化文本顺序编号。服务端校验了逐场覆盖与顺序；"
        "文中的分析判断仍需对照原文核查，修改建议不代表唯一解法。"
    ),
    "colon": "：",
}

_EN = {
    "deck": (
        "Screenplay coverage · {scenes} scenes reviewed in source order · "
        "{characters} principal characters"
    ),
    "conclusions": "1. Key findings",
    "revisions": "Revise first",
    "no_revisions": (
        "This review found no priority revision with sufficient textual support."
    ),
    "strengths": "Worth keeping",
    "no_strengths": "This review does not single out a textual strength.",
    "overview": "2. Story overview",
    "logline": "Logline",
    "synopsis": "Synopsis",
    "structure": "3. Structure and pacing",
    "acts": "Movements",
    "turning_points": "Turning points",
    "pacing": "Pacing",
    "characters": "4. Characters",
    "no_characters": "No principal character is listed separately.",
    "goal": "Goal",
    "conflict": "Opposition",
    "arc": "Change",
    "dialogue": "5. Dialogue",
    "dialogue_findings": "Dialogue findings",
    "appendix": "6. Scene-by-scene notes",
    "appendix_intro": (
        "Notes for each scene in source order, for use alongside the draft."
    ),
    "scene": "Scene {index}",
    "purpose": "Purpose",
    "scene_conflict": "Conflict",
    "turn": "Turn",
    "scene_pacing": "Pacing",
    "no_scene_findings": "No separate finding for this scene.",
    "empty": "No separate finding.",
    "notes": "7. How to read this report",
    "notes_body": (
        "Scenes are numbered in the order of the normalized upload. The server "
        "verified scene coverage and order; analytical judgments should still be "
        "checked against the draft, and revision notes are not the only solution."
    ),
    "colon": ": ",
}

_REWRITE_ZH = {
    "title": "剧本改写稿",
    "source": "源语言",
    "target": "目标语言",
    "scenes": "场景数",
    "glossary": "一、术语表",
    "glossary_header": "| 原文 | 译文 | 类别 |",
    "changes": "二、改写说明",
    "screenplay": "三、改写正文",
    "scene": "第 {index} 场",
    "colon": "：",
}

_REWRITE_EN = {
    "title": "Screenplay rewrite",
    "source": "Source language",
    "target": "Target language",
    "scenes": "Scenes",
    "glossary": "1. Glossary",
    "glossary_header": "| Source | Target | Category |",
    "changes": "2. Changes",
    "screenplay": "3. Rewritten screenplay",
    "scene": "Scene {index}",
    "colon": ": ",
}


def render_screenplay_report_markdown(
    result: ScreenplayAnalysisResult | ScreenplayRewriteResult,
) -> str:
    if isinstance(result, ScreenplayAnalysisResult):
        return _analysis_report(result)
    return _rewrite_report(result)


def _analysis_report(result: ScreenplayAnalysisResult) -> str:
    labels = _ZH if _is_chinese(result.language) else _EN
    lines = [
        f"# {_inline(result.title)}",
        "",
        "> "
        + labels["deck"].format(
            scenes=len(result.scenes), characters=len(result.characters)
        ),
        "",
        f"## {labels['conclusions']}",
        "",
    ]
    _findings(
        lines, labels["revisions"], result.priority_revisions, labels["no_revisions"]
    )
    _findings(lines, labels["strengths"], result.strengths, labels["no_strengths"])
    lines.extend(
        (
            f"## {labels['overview']}",
            "",
            f"### {labels['logline']}",
            "",
            _block(result.logline),
            "",
            f"### {labels['synopsis']}",
            "",
            _block(result.synopsis),
            "",
            f"## {labels['structure']}",
            "",
        )
    )
    _findings(lines, labels["acts"], result.structure.acts, labels["empty"])
    _findings(
        lines,
        labels["turning_points"],
        result.structure.turning_points,
        labels["empty"],
    )
    lines.extend(
        (
            f"### {labels['pacing']}",
            "",
            _block(result.structure.pacing_summary),
            "",
            f"## {labels['characters']}",
            "",
        )
    )
    if not result.characters:
        lines.extend((labels["no_characters"], ""))
    for index, character in enumerate(result.characters, start=1):
        lines.extend((f"### {index}. {_inline(character.name)}", ""))
        for label, value in (
            (labels["goal"], character.goal),
            (labels["conflict"], character.conflict),
            (labels["arc"], character.arc),
        ):
            lines.extend((f"**{label}**{labels['colon']}{_inline(value)}", ""))
    lines.extend((f"## {labels['dialogue']}", ""))
    _findings(
        lines, labels["dialogue_findings"], result.dialogue_findings, labels["empty"]
    )
    lines.extend((f"## {labels['appendix']}", "", labels["appendix_intro"], ""))
    for index, scene in enumerate(result.scenes, start=1):
        lines.extend((f"### {labels['scene'].format(index=index)}", ""))
        for label, value in (
            (labels["purpose"], scene.purpose),
            (labels["scene_conflict"], scene.conflict),
            (labels["turn"], scene.turn),
            (labels["scene_pacing"], scene.pacing),
        ):
            lines.extend((f"**{label}**{labels['colon']}{_inline(value)}", ""))
        if scene.findings:
            lines.extend(f"- {_inline(item)}" for item in scene.findings)
        else:
            lines.append(f"- {labels['no_scene_findings']}")
        lines.append("")
    lines.extend((f"## {labels['notes']}", "", labels["notes_body"], ""))
    return "\n".join(lines).rstrip() + "\n"


def _rewrite_report(result: ScreenplayRewriteResult) -> str:
    labels = _REWRITE_ZH if _is_chinese(result.target_language) else _REWRITE_EN
    colon = labels["colon"]
    lines = [
        f"# {labels['title']}",
        "",
        (
            f"> {labels['source']}{colon}{_inline(result.source_language)} · "
            f"{labels['target']}{colon}{_inline(result.target_language)} · "
            f"{labels['scenes']}{colon}{result.output_scene_count}"
        ),
        "",
        f"## {labels['glossary']}",
        "",
        labels["glossary_header"],
        "|---|---|---|",
    ]
    lines.extend(
        f"| {_inline(item.source)} | {_inline(item.target)} | "
        f"{_inline(item.category)} |"
        for item in result.glossary
    )
    lines.extend(("", f"## {labels['changes']}", ""))
    lines.extend(f"- {_inline(item)}" for item in result.change_summary)
    lines.extend(("", f"## {labels['screenplay']}", ""))
    current_scene = None
    scene_index = 0
    for chunk in result.chunks:
        if chunk.source_scene_id != current_scene:
            current_scene = chunk.source_scene_id
            scene_index += 1
            lines.extend((f"### {labels['scene'].format(index=scene_index)}", ""))
        lines.extend((_body(chunk.rewritten_text), ""))
    return "\n".join(lines).rstrip() + "\n"


def _findings(
    lines: list[str],
    title: str,
    items: tuple[ScreenplayFinding, ...],
    empty_message: str,
) -> None:
    lines.extend((f"### {title}", ""))
    if not items:
        lines.extend((f"> {empty_message}", ""))
        return
    for index, item in enumerate(items, start=1):
        lines.extend(
            (f"**{index}\\. {_inline(item.title)}**", "", _block(item.description), "")
        )


def _is_chinese(language: str) -> bool:
    return language.lower().startswith("zh")


def _inline(value: str) -> str:
    escaped = html.escape(" ".join(value.split()), quote=False)
    return _MARKDOWN_SPECIAL.sub(r"\\\1", escaped)


def _block(value: str) -> str:
    """Keep the model's paragraph breaks; every paragraph is escaped plain text."""
    return "\n\n".join(_inline(part) for part in value.splitlines() if part.strip())


def _body(value: str) -> str:
    return "  \n".join(
        _inline(line) if line.strip() else "" for line in value.splitlines()
    )
