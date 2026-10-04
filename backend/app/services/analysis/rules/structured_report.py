"""Generic evidence-bounded report for Skills that need no bespoke structure.

The contract fixes the shape and limits; a Skill only decides which sections
it asks for. Text is plain (rendered and escaped by the server), so a Skill
cannot inject HTML, links or images into reports.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from app.services.analysis.rules.content_document import ContentReview
from app.services.analysis.rules.editorial_review import (
    ReviewStatus,
    validate_editorial_review,
)
from app.services.analysis.rules.enums import AnalysisResultKind, AnalysisValidationCode
from app.services.analysis.rules.errors import AnalysisValidationError
from app.services.analysis.rules.result_models import (
    AnalysisMedia,
    VideoArticleEvidence,
)
from app.services.analysis.rules.text import required_text

MAX_SECTIONS = 16
MAX_SECTION_ITEMS = 20
MAX_SECTION_EVIDENCE = 12
MAX_LIMITATIONS = 12
_ITEM_CHARACTERS = 1_000


@dataclass(frozen=True, slots=True)
class StructuredReportCitation:
    source_sha256: str
    start: int
    end: int
    quote: str

    def __post_init__(self) -> None:
        if (
            re.fullmatch(r"[a-f0-9]{64}", self.source_sha256) is None
            or type(self.start) is not int
            or type(self.end) is not int
            or not 0 <= self.start < self.end
            or not isinstance(self.quote, str)
            or len(self.quote) != self.end - self.start
            or "\x00" in self.quote
            or len(self.quote.encode("utf-8")) > 1024**2
        ):
            raise AnalysisValidationError(
                AnalysisValidationCode.INVALID_EVIDENCE, "invalid source text citation"
            )


@dataclass(frozen=True, slots=True)
class StructuredReportSection:
    id: str
    heading: str
    body: str
    items: tuple[str, ...]
    evidence: tuple[VideoArticleEvidence, ...]
    citations: tuple[StructuredReportCitation, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "id", required_text(self.id, "report section id", maximum=128)
        )
        object.__setattr__(
            self,
            "heading",
            required_text(self.heading, "report section heading", maximum=200),
        )
        if self.citations:
            if (
                len(self.citations) > 512
                or self.body != "".join(item.quote for item in self.citations)
                or not self.body.strip()
            ):
                raise AnalysisValidationError(
                    AnalysisValidationCode.INVALID_EVIDENCE,
                    "document body must equal its preserved source spans",
                )
        else:
            object.__setattr__(
                self, "body", required_text(self.body, "report section body")
            )
        object.__setattr__(
            self,
            "items",
            _bounded_items(self.items, "report section item", MAX_SECTION_ITEMS),
        )
        if len(self.evidence) > MAX_SECTION_EVIDENCE:
            raise AnalysisValidationError(
                AnalysisValidationCode.LIMIT_EXCEEDED,
                "report section evidence exceeds the item limit",
            )


@dataclass(frozen=True, slots=True)
class StructuredReportResult:
    language: str
    title: str
    summary: str
    sections: tuple[StructuredReportSection, ...]
    limitations: tuple[str, ...]
    media: AnalysisMedia | None
    kind: AnalysisResultKind = field(
        init=False, default=AnalysisResultKind.STRUCTURED_REPORT
    )
    review_status: ReviewStatus = "not_reviewed"
    review_history: tuple[ContentReview, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "language", required_text(self.language, "language", maximum=35)
        )
        object.__setattr__(
            self, "title", required_text(self.title, "title", maximum=200)
        )
        object.__setattr__(
            self, "summary", required_text(self.summary, "report summary")
        )
        if not self.sections or len(self.sections) > MAX_SECTIONS:
            raise AnalysisValidationError(
                AnalysisValidationCode.INVALID_SCHEMA,
                f"report must contain 1 to {MAX_SECTIONS} sections",
            )
        ids = tuple(section.id for section in self.sections)
        if len(set(ids)) != len(ids):
            raise AnalysisValidationError(
                AnalysisValidationCode.DUPLICATE_IDENTIFIER,
                "report section ids must be unique",
            )
        object.__setattr__(
            self,
            "limitations",
            _bounded_items(self.limitations, "report limitation", MAX_LIMITATIONS),
        )
        for section in self.sections:
            if self.media is None and (section.evidence or not section.citations):
                raise AnalysisValidationError(
                    AnalysisValidationCode.INVALID_EVIDENCE,
                    "a document report needs source citations, not media timestamps",
                )
            if self.media is not None and section.citations:
                raise AnalysisValidationError(
                    AnalysisValidationCode.INVALID_EVIDENCE,
                    "video reports cannot pretend to have source text citations",
                )
            for evidence in section.evidence:
                assert self.media is not None
                if (
                    evidence.start_ms >= self.media.duration_ms
                    or evidence.end_ms > self.media.duration_ms
                ):
                    raise AnalysisValidationError(
                        AnalysisValidationCode.INVALID_TIME_RANGE,
                        "report evidence exceeds the authoritative media duration",
                    )
        validate_editorial_review(
            self.review_history, self.review_status, len(self.sections)
        )

    def validate_document_source(self, expected_sha256: str) -> None:
        citations = [item for section in self.sections for item in section.citations]
        position = 0
        for item in citations:
            if item.start != position or item.source_sha256 != expected_sha256:
                raise AnalysisValidationError(
                    AnalysisValidationCode.INVALID_EVIDENCE,
                    "document source spans differ",
                )
            position = item.end
        if (
            self.media is not None
            or not citations
            or hashlib.sha256(
                "".join(item.quote for item in citations).encode()
            ).hexdigest()
            != expected_sha256
        ):
            raise AnalysisValidationError(
                AnalysisValidationCode.INVALID_EVIDENCE,
                "document source hash or full coverage differs",
            )


def _bounded_items(
    values: tuple[str, ...], field_name: str, maximum: int
) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise AnalysisValidationError(
            AnalysisValidationCode.INVALID_SCHEMA, f"{field_name} must be a tuple"
        )
    if len(values) > maximum:
        raise AnalysisValidationError(
            AnalysisValidationCode.LIMIT_EXCEEDED,
            f"{field_name} exceeds the item limit",
        )
    normalized = tuple(
        required_text(value, field_name, maximum=_ITEM_CHARACTERS) for value in values
    )
    if len(set(normalized)) != len(normalized):
        raise AnalysisValidationError(
            AnalysisValidationCode.DUPLICATE_IDENTIFIER,
            f"{field_name} cannot contain duplicates",
        )
    return normalized
