from typing import cast

from app.repositories.analysis.storage_fields import (
    array,
    integer,
    mapping,
    string,
    strings,
)
from app.services.analysis.rules.content_document import ContentReview
from app.services.analysis.rules.editorial_review import ReviewStatus
from app.services.analysis.rules.enums import AnalysisResultKind
from app.services.analysis.rules.result_models import (
    AnalysisMedia,
    VideoArticleEvidence,
)
from app.services.analysis.rules.structured_report import (
    StructuredReportCitation,
    StructuredReportResult,
    StructuredReportSection,
)

_FIELDS = {"kind", "language", "title", "summary", "sections", "limitations", "media"}


def structured_report_from_document(document: object) -> StructuredReportResult:
    optional = (
        set(document) & {"review_status", "review_history"}
        if isinstance(document, dict)
        else set()
    )
    root = mapping(document, _FIELDS | optional, "structured report result")
    if root["kind"] != AnalysisResultKind.STRUCTURED_REPORT.value:
        raise ValueError("stored structured report kind is invalid")
    media = (
        None
        if root["media"] is None
        else mapping(root["media"], {"duration_ms", "container", "size_bytes"}, "media")
    )
    return StructuredReportResult(
        language=string(root["language"], "language"),
        title=string(root["title"], "title"),
        summary=string(root["summary"], "summary"),
        sections=tuple(_section(item) for item in array(root["sections"], "sections")),
        limitations=tuple(strings(root["limitations"], "limitations")),
        review_status=cast(ReviewStatus, root.get("review_status", "not_reviewed")),
        review_history=tuple(
            ContentReview.model_validate(item)
            for item in array(root.get("review_history", []), "review_history")
        ),
        media=None
        if media is None
        else AnalysisMedia(
            duration_ms=integer(media["duration_ms"], "media.duration_ms"),
            container=string(media["container"], "media.container"),
            size_bytes=integer(media["size_bytes"], "media.size_bytes"),
        ),
    )


def _section(value: object) -> StructuredReportSection:
    fields = {"id", "heading", "body", "items", "evidence"}
    if isinstance(value, dict) and "citations" in value:
        fields.add("citations")
    source = mapping(value, fields, "report section")
    body = source["body"]
    if not isinstance(body, str):
        raise ValueError("report body must be text")
    return StructuredReportSection(
        id=string(source["id"], "report section.id"),
        heading=string(source["heading"], "report section.heading"),
        body=body if source.get("citations") else string(body, "report section.body"),
        items=tuple(strings(source["items"], "report section.items")),
        evidence=tuple(
            _evidence(item) for item in array(source["evidence"], "report evidence")
        ),
        citations=tuple(
            _citation(item)
            for item in array(source.get("citations", []), "source citations")
        ),
    )


def _citation(value: object) -> StructuredReportCitation:
    item = mapping(value, {"source_sha256", "start", "end", "quote"}, "source citation")
    quote = item["quote"]
    if not isinstance(quote, str):
        raise ValueError("source quote must be text")
    return StructuredReportCitation(
        string(item["source_sha256"], "source sha256"),
        integer(item["start"], "start"),
        integer(item["end"], "end"),
        quote,
    )


def _evidence(value: object) -> VideoArticleEvidence:
    source = mapping(value, {"start_ms", "end_ms", "note"}, "report evidence")
    return VideoArticleEvidence(
        start_ms=integer(source["start_ms"], "report evidence.start_ms"),
        end_ms=integer(source["end_ms"], "report evidence.end_ms"),
        note=string(source["note"], "report evidence.note"),
    )
