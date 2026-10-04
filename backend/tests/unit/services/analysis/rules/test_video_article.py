from __future__ import annotations

import pytest
from app.services.analysis.rules.errors import AnalysisValidationError
from app.services.analysis.rules.result_models import AnalysisMedia
from app.services.analysis.rules.video_article_parser import parse_video_article_result


def article_payload() -> dict[str, object]:
    return {
        "language": "zh-CN",
        "title": "从一个问题开始理解系统",
        "lead": "这段视频从一个具体问题出发，解释了系统如何逐步形成。",
        "sections": [
            {
                "id": "section-1",
                "title": "问题从哪里出现",
                "body": "视频先用一个具体场景说明问题的起点。",
                "evidence": [
                    {
                        "start_ms": 0,
                        "end_ms": 1_500,
                        "note": "开场出现问题场景和标题文字。",
                    }
                ],
            },
            {
                "id": "section-2",
                "title": "解决思路如何展开",
                "body": "随后视频按步骤展示解决思路，并给出可复用的判断方式。",
                "evidence": [
                    {
                        "start_ms": 1_500,
                        "end_ms": 3_000,
                        "note": "画面展示步骤列表和操作过程。",
                    }
                ],
            },
        ],
        "key_points": ["先定义问题，再选择解决路径。"],
        "closing": "真正重要的是把一次性的经验沉淀为可复用的方法。",
        "limitations": ["当前执行器没有可靠的音频转写，文章不对对白作事实断言。"],
    }


def test_video_article_result_requires_bounded_evidence() -> None:
    result = parse_video_article_result(
        article_payload(),
        AnalysisMedia(duration_ms=3_000, container="mp4", size_bytes=1_024),
        expected_language="zh-CN",
    )

    assert result.kind.value == "video_article"
    assert result.sections[0].evidence[0].end_ms == 1_500

    invalid = article_payload()
    sections = invalid["sections"]
    assert isinstance(sections, list)
    evidence = sections[0]["evidence"]
    assert isinstance(evidence, list)
    evidence[0]["end_ms"] = 3_001
    with pytest.raises(AnalysisValidationError):
        parse_video_article_result(
            invalid,
            AnalysisMedia(duration_ms=3_000, container="mp4", size_bytes=1_024),
            expected_language="zh-CN",
        )


@pytest.mark.parametrize(
    "start,end,valid",
    [(0, 0, True), (2999, 2999, True), (3000, 3000, False), (1500, 1000, False)],
)
def test_article_frame_evidence_is_a_bounded_point(
    start: int, end: int, valid: bool
) -> None:
    value = article_payload()
    value["sections"][0]["evidence"][0].update(start_ms=start, end_ms=end)

    def parse():
        return parse_video_article_result(
            value,
            AnalysisMedia(duration_ms=3000, container="mp4", size_bytes=1024),
            expected_language="zh-CN",
        )

    if valid:
        assert parse().sections[0].evidence[0].start_ms == start
    else:
        with pytest.raises(AnalysisValidationError):
            parse()
