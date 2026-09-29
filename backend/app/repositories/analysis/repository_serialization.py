"""Strict current-state serialization for every analysis result contract."""

from collections.abc import Callable
from typing import Any

from app.repositories.analysis.screenplay_rewrite_serialization import (
    screenplay_rewrite_from_document,
)
from app.repositories.analysis.screenplay_serialization import (
    screenplay_analysis_from_document,
)
from app.repositories.analysis.storage_fields import dataclass_document, mapping
from app.repositories.analysis.structured_report_serialization import (
    structured_report_from_document,
)
from app.repositories.analysis.video_article_serialization import (
    video_article_from_document,
)
from app.repositories.analysis.video_serialization import video_result_from_document
from app.services.analysis.rules.contracts import contract_for_result
from app.services.analysis.rules.enums import AnalysisResultKind
from app.services.analysis.rules.result_types import AnalysisResult


def analysis_result_document(result: AnalysisResult) -> dict[str, Any]:
    result_kind(result)
    return dataclass_document(result)


_FROM_DOCUMENT: dict[AnalysisResultKind, Callable[[dict[str, Any]], AnalysisResult]] = {
    AnalysisResultKind.VIDEO_VISUAL_ANALYSIS: video_result_from_document,
    AnalysisResultKind.VIDEO_ARTICLE: video_article_from_document,
    AnalysisResultKind.SCREENPLAY_ANALYSIS: screenplay_analysis_from_document,
    AnalysisResultKind.SCREENPLAY_REWRITE: screenplay_rewrite_from_document,
    AnalysisResultKind.STRUCTURED_REPORT: structured_report_from_document,
}


def analysis_result_from_document(document: object) -> AnalysisResult:
    root = mapping(document, None, "analysis result")
    raw_kind = root.get("kind")
    try:
        kind = AnalysisResultKind(raw_kind if isinstance(raw_kind, str) else "")
    except ValueError:
        raise ValueError("stored analysis result has an unknown kind") from None
    return _FROM_DOCUMENT[kind](root)


def result_kind(result: AnalysisResult) -> AnalysisResultKind:
    return contract_for_result(result).kind
