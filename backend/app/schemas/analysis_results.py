from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import Field, TypeAdapter

from app.schemas.common import StrictModel
from app.services.analysis.rules.content_document import (
    ContentDocumentResult,
    ContentReview,
)
from app.services.analysis.rules.editorial_review import ReviewStatus


def _omit_default(schema: dict[str, Any]) -> None:
    # dart-dio enum defaults use Python wire names as Dart identifiers.
    schema.pop("default", None)


class AnalysisMediaResponse(StrictModel):
    duration_ms: int
    container: str
    size_bytes: int


class EvidenceSummaryResponse(StrictModel):
    text: str
    evidence_shot_ids: tuple[str, ...]


class ShotResponse(StrictModel):
    id: str
    index: int
    start_ms: int
    end_ms: int
    representative_frame_ms: int
    description: str
    transition_in: str
    shot_size: str
    camera_motion: str
    narrative_function: str
    highlight_score: int
    visual_tags: tuple[str, ...]
    asset_ids: tuple[str, ...]


class HighlightResponse(StrictModel):
    id: str
    title: str
    description: str
    score: int
    reason: str
    start_ms: int
    end_ms: int
    evidence_shot_ids: tuple[str, ...]


class VideoSceneResponse(StrictModel):
    id: str
    index: int
    title: str
    start_ms: int
    end_ms: int
    location: str
    description: str
    narrative_function: str
    visual_rules: tuple[str, ...]
    continuity_risks: tuple[str, ...]
    evidence_shot_ids: tuple[str, ...]


class VisualAssetResponse(StrictModel):
    id: str
    type: str
    label: str
    description: str
    first_seen_ms: int
    evidence_shot_ids: tuple[str, ...]


class ProductionAdviceResponse(StrictModel):
    summary: str
    priority_shot_ids: tuple[str, ...]
    recommended_extensions: tuple[str, ...]


class VideoAnalysisResultResponse(StrictModel):
    kind: Literal["video_visual_analysis"] = Field(
        json_schema_extra={"enum": ["video_visual_analysis"]}
    )
    language: str
    title: str
    summary: EvidenceSummaryResponse
    media: AnalysisMediaResponse
    shot_count: int
    shots: tuple[ShotResponse, ...]
    scenes: tuple[VideoSceneResponse, ...]
    highlights: tuple[HighlightResponse, ...]
    assets: tuple[VisualAssetResponse, ...]
    production_advice: ProductionAdviceResponse


class VideoArticleEvidenceResponse(StrictModel):
    start_ms: int
    end_ms: int
    note: str


class VideoArticleSectionResponse(StrictModel):
    id: str
    title: str
    body: str
    evidence: tuple[VideoArticleEvidenceResponse, ...]


class VideoArticleResultResponse(StrictModel):
    kind: Literal["video_article"] = Field(
        json_schema_extra={"enum": ["video_article"]}
    )
    language: str
    title: str
    lead: str
    sections: tuple[VideoArticleSectionResponse, ...]
    key_points: tuple[str, ...]
    closing: str
    limitations: tuple[str, ...]
    media: AnalysisMediaResponse
    review_status: ReviewStatus = Field(
        default="not_reviewed", json_schema_extra=_omit_default
    )
    review_history: tuple[ContentReview, ...] = ()


class ScreenplayFindingResponse(StrictModel):
    id: str
    title: str
    description: str


class ScreenplayStructureResponse(StrictModel):
    acts: tuple[ScreenplayFindingResponse, ...]
    turning_points: tuple[ScreenplayFindingResponse, ...]
    pacing_summary: str


class ScreenplayCharacterResponse(StrictModel):
    id: str
    name: str
    goal: str
    conflict: str
    arc: str


class ScreenplaySceneResponse(StrictModel):
    id: str
    source_scene_id: str
    purpose: str
    conflict: str
    turn: str
    pacing: str
    findings: tuple[str, ...]


class ScreenplayAnalysisResultResponse(StrictModel):
    kind: Literal["screenplay_analysis"] = Field(
        json_schema_extra={"enum": ["screenplay_analysis"]}
    )
    language: str
    title: str
    logline: str
    synopsis: str
    structure: ScreenplayStructureResponse
    characters: tuple[ScreenplayCharacterResponse, ...]
    scenes: tuple[ScreenplaySceneResponse, ...]
    dialogue_findings: tuple[ScreenplayFindingResponse, ...]
    strengths: tuple[ScreenplayFindingResponse, ...]
    priority_revisions: tuple[ScreenplayFindingResponse, ...]


class ScreenplayGlossaryTermResponse(StrictModel):
    source: str
    target: str
    category: str


class ScreenplayRewriteResultResponse(StrictModel):
    kind: Literal["screenplay_rewrite"] = Field(
        json_schema_extra={"enum": ["screenplay_rewrite"]}
    )
    source_language: str
    target_language: str
    source_scene_count: int
    output_scene_count: int
    glossary: tuple[ScreenplayGlossaryTermResponse, ...]
    change_summary: tuple[str, ...]


class StructuredReportSectionResponse(StrictModel):
    id: str
    heading: str
    body: str
    items: tuple[str, ...]
    evidence: tuple[VideoArticleEvidenceResponse, ...]


class StructuredReportResultResponse(StrictModel):
    kind: Literal["structured_report"] = Field(
        json_schema_extra={"enum": ["structured_report"]}
    )
    language: str
    title: str
    summary: str
    sections: tuple[StructuredReportSectionResponse, ...]
    limitations: tuple[str, ...]
    media: AnalysisMediaResponse
    review_status: ReviewStatus = Field(
        default="not_reviewed", json_schema_extra=_omit_default
    )
    review_history: tuple[ContentReview, ...] = ()


AnalysisResultResponse: TypeAlias = Annotated[  # noqa: UP040
    ContentDocumentResult
    | VideoAnalysisResultResponse
    | VideoArticleResultResponse
    | ScreenplayAnalysisResultResponse
    | ScreenplayRewriteResultResponse
    | StructuredReportResultResponse,
    Field(discriminator="kind"),
]

ANALYSIS_RESULT_RESPONSE_ADAPTER: TypeAdapter[AnalysisResultResponse] = TypeAdapter(
    AnalysisResultResponse
)
