"""Strict, local subtitle interchange; overlapping dialogue is intentionally legal."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

SubtitleFormat = Literal["srt", "vtt"]
_TIMING = re.compile(
    r"^(?P<start>(?:\d{2,}:)?\d{2}:\d{2}[,.]\d{3})"
    r"\s+-->\s+(?P<end>(?:\d{2,}:)?\d{2}:\d{2}[,.]\d{3})$"
)


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    start_ms: int
    end_ms: int
    text: str
    identifier: str | None = None


def _timestamp(value: str, format: SubtitleFormat) -> int:
    separator = "," if format == "srt" else "."
    if separator not in value:
        raise ValueError("字幕时间格式与文件类型不一致")
    whole, fraction = value.split(separator)
    units = whole.split(":")
    if format == "srt" and len(units) != 3:
        raise ValueError("SRT 时间需要时、分、秒")
    if len(units) == 2:
        hours, minutes, seconds = 0, int(units[0]), int(units[1])
    elif len(units) == 3:
        hours, minutes, seconds = map(int, units)
    else:
        raise ValueError("无效字幕时间")
    if minutes >= 60 or seconds >= 60:
        raise ValueError("字幕分秒必须小于 60")
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + int(fraction)


def validate_subtitles(
    cues: Sequence[SubtitleCue], *, duration_ms: int | None = None
) -> None:
    if not cues or len(cues) > 20_000:
        raise ValueError("字幕需要 1～20,000 条对白")
    if duration_ms is not None and duration_ms <= 0:
        raise ValueError("媒体时长必须为正数")
    previous_start = -1
    for cue in cues:
        if (
            isinstance(cue.start_ms, bool)
            or isinstance(cue.end_ms, bool)
            or not isinstance(cue.start_ms, int)
            or not isinstance(cue.end_ms, int)
            or cue.start_ms < 0
            or cue.end_ms <= cue.start_ms
        ):
            raise ValueError("字幕起止时间无效")
        if cue.start_ms < previous_start:
            raise ValueError("字幕须按开始时间排列；合法重叠可保留")
        if duration_ms is not None and cue.end_ms > duration_ms:
            raise ValueError("字幕超出原始媒体范围")
        if (
            not cue.text.strip()
            or len(cue.text) > 10_000
            or "\x00" in cue.text
            or "-->" in cue.text
            or "\n\n" in cue.text.replace("\r\n", "\n")
        ):
            raise ValueError("字幕正文为空或不能安全交换")
        if cue.identifier is not None and (
            not cue.identifier.strip()
            or "\n" in cue.identifier
            or "\r" in cue.identifier
            or "-->" in cue.identifier
        ):
            raise ValueError("字幕标识不能包含换行或时间箭头")
        previous_start = cue.start_ms


def parse_subtitles(
    text: str,
    format: SubtitleFormat = "srt",
    *,
    duration_ms: int | None = None,
) -> list[SubtitleCue]:
    if format not in ("srt", "vtt"):
        raise ValueError("仅支持 SRT 和 WebVTT")
    if len(text.encode("utf-8")) > 8 * 1024 * 1024:
        raise ValueError("字幕文件超过 8 MiB")
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if format == "vtt":
        lines = normalized.split("\n")
        if not lines or lines[0].strip() != "WEBVTT":
            raise ValueError("WebVTT 缺少 WEBVTT 文件头")
        normalized = "\n".join(lines[1:])
    elif normalized.startswith("WEBVTT"):
        raise ValueError("文件内容是 WebVTT 而不是 SRT")
    cues: list[SubtitleCue] = []
    for block in re.split(r"\n[ \t]*\n", normalized.strip()):
        if not block.strip():
            continue
        lines = block.split("\n")
        if format == "vtt" and lines[0].startswith(("NOTE", "STYLE", "REGION")):
            raise ValueError("本字幕校订不支持 NOTE、STYLE 或 REGION 块")
        identifier: str | None = None
        if "-->" not in lines[0]:
            identifier = lines.pop(0).strip()
            if format == "srt" and not identifier.isdecimal():
                raise ValueError("SRT 序号须为数字")
        if not lines:
            raise ValueError("字幕块没有时间和正文")
        match = _TIMING.fullmatch(lines.pop(0).strip())
        if match is None:
            raise ValueError("字幕时间无效或包含尚未支持的定位设置")
        cues.append(
            SubtitleCue(
                _timestamp(match["start"], format),
                _timestamp(match["end"], format),
                "\n".join(lines),
                identifier,
            )
        )
    validate_subtitles(cues, duration_ms=duration_ms)
    return cues


def _format_timestamp(milliseconds: int, format: SubtitleFormat) -> str:
    seconds, fraction = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    separator = "," if format == "srt" else "."
    return f"{hours:02}:{minutes:02}:{seconds:02}{separator}{fraction:03}"


def export_subtitles(
    cues: Sequence[SubtitleCue],
    format: SubtitleFormat = "srt",
    *,
    duration_ms: int | None = None,
) -> bytes:
    if format not in ("srt", "vtt"):
        raise ValueError("仅支持 SRT 和 WebVTT")
    validate_subtitles(cues, duration_ms=duration_ms)
    blocks = []
    for index, cue in enumerate(cues, 1):
        identifier = str(index) if format == "srt" else cue.identifier
        timing = (
            f"{_format_timestamp(cue.start_ms, format)} --> "
            f"{_format_timestamp(cue.end_ms, format)}"
        )
        parts = ([identifier] if identifier else []) + [timing, cue.text]
        blocks.append("\n".join(parts))
    prefix = "WEBVTT\n\n" if format == "vtt" else ""
    return (prefix + "\n\n".join(blocks) + "\n").encode("utf-8")
