"""Self-contained report body and exact source evidence for built-in Skills."""

from app.services.analysis.report_formatting import markdown_text
from app.services.skills.models import SkillReportResult


def render_skill_report_markdown(result: SkillReportResult) -> str:
    lines = [f"# {markdown_text(result.title)}", ""]
    if result.summary:
        lines.extend([markdown_text(result.summary), ""])
    lines.extend([result.body, ""])
    if result.evidence:
        lines.extend(["## 原文依据", ""])
        for index, reference in enumerate(result.evidence, 1):
            lines.extend(
                [
                    f"### 引用 {index} · {reference.source_id}",
                    "",
                    f"{markdown_text(reference.claim)}（{reference.status}）",
                    "",
                    f"- 正文 SHA-256：`{reference.sha256}`",
                    f"- Unicode 字符范围：[{reference.start}, {reference.end})",
                    "",
                    "> " + markdown_text(reference.quote),
                    "",
                ]
            )
    if result.media_evidence:
        lines.extend(["## 实际画面依据", ""])
        frames = result.data.get("frames", [])
        by_id = (
            {str(frame.get("id")): frame for frame in frames if isinstance(frame, dict)}
            if isinstance(frames, list)
            else {}
        )
        for index, visual_reference in enumerate(result.media_evidence, 1):
            frame = by_id.get(visual_reference.frame_id, {})
            lines.extend(
                [
                    f"### 画面 {index} · {visual_reference.frame_id}",
                    "",
                    f"{markdown_text(visual_reference.claim)}（{visual_reference.status}）",
                    "",
                    f"- 原视频 SHA-256：`{visual_reference.sha256}`",
                    f"- 真实时码：{visual_reference.timestamp_ms} ms",
                    f"- 帧 PNG SHA-256：`{visual_reference.frame_sha256}`",
                    f"- 来源槽：{visual_reference.source_id}",
                    "",
                ]
            )
            if frame.get("shot_id"):
                lines.extend(
                    [f"- 镜头候选：{markdown_text(str(frame['shot_id']))}", ""]
                )
    sources = result.data.get("sources", [])
    if isinstance(sources, list) and sources:
        lines.extend(["## 固定来源", ""])
        for source in sources:
            if not isinstance(source, dict):
                continue
            source_id = markdown_text(str(source.get("source_id", "")))
            title = markdown_text(str(source.get("title", "输入来源")))
            lines.append(
                f"- {source_id}：{title}；SHA-256 `{source.get('sha256', '')}`"
            )
            if source.get("original_sha256"):
                lines.append(
                    f"  - 原文件 SHA-256：`{source['original_sha256']}`"
                    "（与提取正文摘要分别记录）"
                )
        lines.append("")
    if result.limitations:
        lines.extend(["## 限制与待核", ""])
        lines.extend(f"- {markdown_text(value)}" for value in result.limitations)
    return "\n".join(lines).rstrip() + "\n"
