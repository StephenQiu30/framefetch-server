from __future__ import annotations

from dataclasses import dataclass, field

from app.services.analysis.rules.content_document import ContentReview
from app.services.analysis.rules.editorial_review import (
    ReviewStatus,
    validate_editorial_review,
)
from app.services.analysis.rules.enums import AnalysisResultKind, AnalysisValidationCode
from app.services.analysis.rules.errors import AnalysisValidationError
from app.services.analysis.rules.result_items import (
    Highlight,
    Shot,
    VisualAsset,
    _references,
    _strings,
)
from app.services.analysis.rules.text import non_negative_integer, required_text
from app.services.analysis.rules.video_scene import VideoScene


@dataclass(frozen=True, slots=True)
class AnalysisLimits:
    max_collection_items: int = 512
    max_string_characters: int = 8_000
    max_total_characters: int = 200_000

    def __post_init__(self) -> None:
        values = (
            self.max_collection_items,
            self.max_string_characters,
            self.max_total_characters,
        )
        if any(isinstance(value, bool) or value <= 0 for value in values):
            raise ValueError("analysis limits must be positive")


@dataclass(frozen=True, slots=True)
class AnalysisMedia:
    duration_ms: int
    container: str
    size_bytes: int

    def __post_init__(self) -> None:
        duration = non_negative_integer(self.duration_ms, "media duration_ms")
        size = non_negative_integer(self.size_bytes, "media size_bytes")
        if duration == 0 or size == 0:
            raise AnalysisValidationError(
                AnalysisValidationCode.INVALID_TIME_RANGE,
                "media duration and size must be positive",
            )
        object.__setattr__(
            self,
            "container",
            required_text(self.container, "media container", maximum=16),
        )


@dataclass(frozen=True, slots=True)
class EvidenceSummary:
    text: str
    evidence_shot_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", required_text(self.text, "summary text"))
        object.__setattr__(
            self,
            "evidence_shot_ids",
            _references(self.evidence_shot_ids, "summary evidence shot id"),
        )


@dataclass(frozen=True, slots=True)
class ProductionAdvice:
    summary: str
    priority_shot_ids: tuple[str, ...]
    recommended_extensions: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "summary", required_text(self.summary, "production advice summary")
        )
        object.__setattr__(
            self,
            "priority_shot_ids",
            _references(self.priority_shot_ids, "production advice shot id"),
        )
        extensions = _strings(
            self.recommended_extensions, "production advice extension"
        )
        if not extensions:
            raise AnalysisValidationError(
                AnalysisValidationCode.INVALID_SCHEMA,
                "production advice extensions cannot be empty",
            )
        object.__setattr__(self, "recommended_extensions", extensions)


@dataclass(frozen=True, slots=True)
class VideoAnalysisResult:
    language: str
    title: str
    summary: EvidenceSummary
    media: AnalysisMedia
    shot_count: int
    shots: tuple[Shot, ...]
    scenes: tuple[VideoScene, ...]
    highlights: tuple[Highlight, ...]
    assets: tuple[VisualAsset, ...]
    production_advice: ProductionAdvice
    kind: AnalysisResultKind = field(
        init=False, default=AnalysisResultKind.VIDEO_VISUAL_ANALYSIS
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "language", required_text(self.language, "language", maximum=35)
        )
        object.__setattr__(self, "title", required_text(self.title, "title"))
        if not self.shots or self.shot_count != len(self.shots):
            raise AnalysisValidationError(
                AnalysisValidationCode.INVALID_SCHEMA,
                "shot_count must equal a non-empty shots collection",
            )
        if not self.scenes:
            raise AnalysisValidationError(
                AnalysisValidationCode.INVALID_SCHEMA,
                "video analysis must contain at least one scene",
            )


@dataclass(frozen=True, slots=True)
class VideoArticleEvidence:
    start_ms: int
    end_ms: int
    note: str

    def __post_init__(self) -> None:
        start = non_negative_integer(self.start_ms, "article evidence start_ms")
        end = non_negative_integer(self.end_ms, "article evidence end_ms")
        if start >= end:
            raise AnalysisValidationError(
                AnalysisValidationCode.INVALID_TIME_RANGE,
                "article evidence must have a positive time range",
            )
        object.__setattr__(self, "start_ms", start)
        object.__setattr__(self, "end_ms", end)
        object.__setattr__(
            self, "note", required_text(self.note, "article evidence note")
        )


@dataclass(frozen=True, slots=True)
class VideoArticleSection:
    id: str
    title: str
    body: str
    evidence: tuple[VideoArticleEvidence, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "id", required_text(self.id, "article section id", maximum=128)
        )
        object.__setattr__(
            self,
            "title",
            required_text(self.title, "article section title", allow_empty=True),
        )
        object.__setattr__(
            self, "body", required_text(self.body, "article section body")
        )
        if not self.evidence:
            raise AnalysisValidationError(
                AnalysisValidationCode.INVALID_EVIDENCE,
                "article sections must include evidence",
            )


@dataclass(frozen=True, slots=True)
class VideoArticleResult:
    language: str
    title: str
    lead: str
    sections: tuple[VideoArticleSection, ...]
    key_points: tuple[str, ...]
    closing: str
    limitations: tuple[str, ...]
    media: AnalysisMedia
    kind: AnalysisResultKind = field(
        init=False, default=AnalysisResultKind.VIDEO_ARTICLE
    )
    review_status: ReviewStatus = "not_reviewed"
    review_history: tuple[ContentReview, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "language", required_text(self.language, "language", maximum=35)
        )
        object.__setattr__(self, "title", required_text(self.title, "title"))
        object.__setattr__(
            self, "lead", required_text(self.lead, "article lead", allow_empty=True)
        )
        object.__setattr__(
            self,
            "closing",
            required_text(self.closing, "article closing", allow_empty=True),
        )
        if not self.sections or len(self.sections) > 12:
            raise AnalysisValidationError(
                AnalysisValidationCode.INVALID_SCHEMA,
                "article must contain 1 to 12 sections",
            )
        ids = tuple(section.id for section in self.sections)
        if len(set(ids)) != len(ids):
            raise AnalysisValidationError(
                AnalysisValidationCode.DUPLICATE_IDENTIFIER,
                "article section ids must be unique",
            )
        if len(self.key_points) > 24:
            raise AnalysisValidationError(
                AnalysisValidationCode.INVALID_SCHEMA,
                "article key points exceed the limit",
            )
        if len(self.limitations) > 12:
            raise AnalysisValidationError(
                AnalysisValidationCode.LIMIT_EXCEEDED,
                "article limitations exceed the item limit",
            )
        object.__setattr__(
            self, "key_points", _strings(self.key_points, "article key point")
        )
        object.__setattr__(
            self, "limitations", _strings(self.limitations, "article limitation")
        )
        for section in self.sections:
            for evidence in section.evidence:
                if evidence.end_ms > self.media.duration_ms:
                    raise AnalysisValidationError(
                        AnalysisValidationCode.INVALID_TIME_RANGE,
                        "article evidence exceeds the authoritative media duration",
                    )
        validate_editorial_review(
            self.review_history, self.review_status, len(self.sections)
        )
