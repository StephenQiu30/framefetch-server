from app.repositories.analysis.storage_fields import (
    array,
    integer,
    mapping,
    string,
    strings,
)
from app.services.analysis.rules.enums import AnalysisResultKind
from app.services.analysis.rules.result_models import (
    AnalysisMedia,
    VideoArticleEvidence,
)
from app.services.analysis.rules.structured_report import (
    StructuredReportResult,
    StructuredReportSection,
)

_FIELDS = {"kind", "language", "title", "summary", "sections", "limitations", "media"}


def structured_report_from_document(document: object) -> StructuredReportResult:
    root = mapping(document, _FIELDS, "structured report result")
    if root["kind"] != AnalysisResultKind.STRUCTURED_REPORT.value:
        raise ValueError("stored structured report kind is invalid")
    media = mapping(root["media"], {"duration_ms", "container", "size_bytes"}, "media")
    return StructuredReportResult(
        language=string(root["language"], "language"),
        title=string(root["title"], "title"),
        summary=string(root["summary"], "summary"),
        sections=tuple(_section(item) for item in array(root["sections"], "sections")),
        limitations=tuple(strings(root["limitations"], "limitations")),
        media=AnalysisMedia(
            duration_ms=integer(media["duration_ms"], "media.duration_ms"),
            container=string(media["container"], "media.container"),
            size_bytes=integer(media["size_bytes"], "media.size_bytes"),
        ),
    )


def _section(value: object) -> StructuredReportSection:
    source = mapping(
        value, {"id", "heading", "body", "items", "evidence"}, "report section"
    )
    return StructuredReportSection(
        id=string(source["id"], "report section.id"),
        heading=string(source["heading"], "report section.heading"),
        body=string(source["body"], "report section.body"),
        items=tuple(strings(source["items"], "report section.items")),
        evidence=tuple(
            _evidence(item) for item in array(source["evidence"], "report evidence")
        ),
    )


def _evidence(value: object) -> VideoArticleEvidence:
    source = mapping(value, {"start_ms", "end_ms", "note"}, "report evidence")
    return VideoArticleEvidence(
        start_ms=integer(source["start_ms"], "report evidence.start_ms"),
        end_ms=integer(source["end_ms"], "report evidence.end_ms"),
        note=string(source["note"], "report evidence.note"),
    )
