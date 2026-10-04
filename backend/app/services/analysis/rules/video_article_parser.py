from __future__ import annotations

from app.services.analysis.rules.enums import AnalysisValidationCode
from app.services.analysis.rules.errors import AnalysisValidationError
from app.services.analysis.rules.parse_helpers import ParseContext
from app.services.analysis.rules.result_models import (
    AnalysisLimits,
    AnalysisMedia,
    VideoArticleEvidence,
    VideoArticleResult,
    VideoArticleSection,
)


def parse_video_article_result(
    payload: object,
    media: AnalysisMedia,
    *,
    expected_language: str,
    limits: AnalysisLimits | None = None,
) -> VideoArticleResult:
    context = ParseContext(limits or AnalysisLimits())
    root = context.mapping(
        payload,
        "result",
        {
            "language",
            "title",
            "lead",
            "sections",
            "key_points",
            "closing",
            "limitations",
        },
    )
    language = context.text(root["language"], "language", maximum=35)
    if language != expected_language:
        raise AnalysisValidationError(
            AnalysisValidationCode.INVALID_SCHEMA,
            "output language does not match the job",
        )
    sections = tuple(
        _section(context, value, index)
        for index, value in enumerate(
            context.array(root["sections"], "sections", allow_empty=False)
        )
    )
    key_points = tuple(
        context.text(value, f"key_points[{index}]")
        for index, value in enumerate(
            context.array(root["key_points"], "key_points", allow_empty=True)
        )
    )
    limitations = tuple(
        context.text(value, f"limitations[{index}]")
        for index, value in enumerate(
            context.array(root["limitations"], "limitations", allow_empty=True)
        )
    )
    return VideoArticleResult(
        language=language,
        title=context.text(root["title"], "title"),
        lead=context.text(root["lead"], "lead", allow_empty=True),
        sections=sections,
        key_points=key_points,
        closing=context.text(root["closing"], "closing", allow_empty=True),
        limitations=limitations,
        media=media,
    )


def _section(context: ParseContext, value: object, index: int) -> VideoArticleSection:
    path = f"sections[{index}]"
    source = context.mapping(value, path, {"id", "title", "body", "evidence"})
    evidence = tuple(
        _evidence(context, item, f"{path}.evidence[{evidence_index}]")
        for evidence_index, item in enumerate(
            context.array(source["evidence"], f"{path}.evidence", allow_empty=False)
        )
    )
    return VideoArticleSection(
        id=context.text(source["id"], f"{path}.id", maximum=128),
        title=context.text(source["title"], f"{path}.title", allow_empty=True),
        body=context.text(source["body"], f"{path}.body"),
        evidence=evidence,
    )


def _evidence(context: ParseContext, value: object, path: str) -> VideoArticleEvidence:
    source = context.mapping(value, path, {"start_ms", "end_ms", "note"})
    return VideoArticleEvidence(
        start_ms=context.integer(source["start_ms"], f"{path}.start_ms"),
        end_ms=context.integer(source["end_ms"], f"{path}.end_ms"),
        note=context.text(source["note"], f"{path}.note"),
    )
