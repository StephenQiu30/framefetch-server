from __future__ import annotations

import pytest
from app.services.creation.subtitles import (
    SubtitleCue,
    export_subtitles,
    parse_subtitles,
    validate_subtitles,
)


def test_subtitles_roundtrip_preserves_chinese_multiline_and_overlap() -> None:
    cues = [
        SubtitleCue(500, 2500, "甲：你好。\n再说一句", "speaker-a"),
        SubtitleCue(2000, 3200, "乙：你好。", "speaker-b"),
    ]
    for format in ("srt", "vtt"):
        content = export_subtitles(cues, format, duration_ms=4000)
        parsed = parse_subtitles(content.decode(), format, duration_ms=4000)
        assert [(cue.start_ms, cue.end_ms, cue.text) for cue in parsed] == [
            (cue.start_ms, cue.end_ms, cue.text) for cue in cues
        ]
        assert parsed[1].start_ms < parsed[0].end_ms
    assert (
        parse_subtitles(export_subtitles(cues, "vtt").decode(), "vtt")[0].identifier
        == "speaker-a"
    )


@pytest.mark.parametrize(
    "text,format",
    [
        ("1\n00:00:60,000 --> 00:00:61,000\n不合法", "srt"),
        ("1\n00:00:01,000 --> 00:00:00,500\n反向", "srt"),
        ("1\n00:00:01.000 --> 00:00:02.000\n错分隔", "srt"),
        ("00:01.000 --> 00:02.000\n缺文件头", "vtt"),
        ("WEBVTT\n\n00:01.000 --> 00:02.000 line:50%\n尚不支持", "vtt"),
        ("WEBVTT\n\nSTYLE\n::cue {color:red}", "vtt"),
        ("", "srt"),
    ],
)
def test_bad_subtitles_are_rejected_without_fabricated_cues(
    text: str, format: str
) -> None:
    with pytest.raises(ValueError):
        parse_subtitles(text, format)  # type: ignore[arg-type]


def test_bounds_unsorted_and_unsafe_text_are_rejected() -> None:
    with pytest.raises(ValueError, match="范围"):
        validate_subtitles([SubtitleCue(0, 3000, "超出")], duration_ms=2000)
    with pytest.raises(ValueError, match="排列"):
        validate_subtitles([SubtitleCue(2000, 3000, "二"), SubtitleCue(0, 1000, "一")])
    with pytest.raises(ValueError, match="交换"):
        export_subtitles([SubtitleCue(0, 1000, "正文\n\n00:01.000 --> 00:02.000")])


def test_vtt_short_time_bom_and_crlf() -> None:
    cues = parse_subtitles(
        "\ufeffWEBVTT\r\n\r\nname\r\n00:01.125 --> 00:02.250\r\n中文", "vtt"
    )
    assert cues == [SubtitleCue(1125, 2250, "中文", "name")]
