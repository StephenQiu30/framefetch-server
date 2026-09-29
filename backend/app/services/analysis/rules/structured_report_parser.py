from __future__ import annotations

from app.services.analysis.rules.enums import AnalysisValidationCode
from app.services.analysis.rules.errors import AnalysisValidationError
from app.services.analysis.rules.parse_helpers import ParseContext
from app.services.analysis.rules.result_models import (
    AnalysisLimits,
    AnalysisMedia,
    VideoArticleEvidence,
)
from app.services.analysis.rules.structured_report import (
    StructuredReportResult,
    StructuredReportSection,
)


def parse_structured_report_result(
    payload: object,
    media: AnalysisMedia,
    *,
    expected_language: str,
    limits: AnalysisLimits | None = None,
) -> StructuredReportResult:
    context = ParseContext(limits or AnalysisLimits())
    root = context.mapping(
        payload,
        "result",
        {"language", "title", "summary", "sections", "limitations"},
    )
    language = context.text(root["language"], "language", maximum=35)
    if language != expected_language:
        raise AnalysisValidationError(
            AnalysisValidationCode.INVALID_SCHEMA,
            "output language does not match the job",
        )
    return StructuredReportResult(
        language=language,
        title=context.text(root["title"], "title", maximum=200),
        summary=context.text(root["summary"], "summary"),
        sections=tuple(
            _section(context, value, index)
            for index, value in enumerate(
                context.array(root["sections"], "sections", allow_empty=False)
            )
        ),
        limitations=_texts(context, root["limitations"], "limitations"),
        media=media,
    )


def _section(
    context: ParseContext, value: object, index: int
) -> StructuredReportSection:
    path = f"sections[{index}]"
    source = context.mapping(
        value, path, {"id", "heading", "body", "items", "evidence"}
    )
    return StructuredReportSection(
        id=context.text(source["id"], f"{path}.id", maximum=128),
        heading=context.text(source["heading"], f"{path}.heading", maximum=200),
        body=context.text(source["body"], f"{path}.body"),
        items=_texts(context, source["items"], f"{path}.items"),
        evidence=tuple(
            _evidence(context, item, f"{path}.evidence[{evidence_index}]")
            for evidence_index, item in enumerate(
                context.array(source["evidence"], f"{path}.evidence", allow_empty=True)
            )
        ),
    )


def _texts(context: ParseContext, value: object, path: str) -> tuple[str, ...]:
    return tuple(
        context.text(item, f"{path}[{index}]", maximum=1_000)
        for index, item in enumerate(context.array(value, path, allow_empty=True))
    )


def _evidence(context: ParseContext, value: object, path: str) -> VideoArticleEvidence:
    source = context.mapping(value, path, {"start_ms", "end_ms", "note"})
    return VideoArticleEvidence(
        start_ms=context.integer(source["start_ms"], f"{path}.start_ms"),
        end_ms=context.integer(source["end_ms"], f"{path}.end_ms"),
        note=context.text(source["note"], f"{path}.note"),
    )
