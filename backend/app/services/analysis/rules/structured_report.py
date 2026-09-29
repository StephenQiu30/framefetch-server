"""Generic evidence-bounded report for Skills that need no bespoke structure.

The contract fixes the shape and limits; a Skill only decides which sections
it asks for. Text is plain (rendered and escaped by the server), so a Skill
cannot inject HTML, links or images into reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
class StructuredReportSection:
    id: str
    heading: str
    body: str
    items: tuple[str, ...]
    evidence: tuple[VideoArticleEvidence, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "id", required_text(self.id, "report section id", maximum=128)
        )
        object.__setattr__(
            self,
            "heading",
            required_text(self.heading, "report section heading", maximum=200),
        )
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
    media: AnalysisMedia
    kind: AnalysisResultKind = field(
        init=False, default=AnalysisResultKind.STRUCTURED_REPORT
    )

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
            for evidence in section.evidence:
                if evidence.end_ms > self.media.duration_ms:
                    raise AnalysisValidationError(
                        AnalysisValidationCode.INVALID_TIME_RANGE,
                        "report evidence exceeds the authoritative media duration",
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
