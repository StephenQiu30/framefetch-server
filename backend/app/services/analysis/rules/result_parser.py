from __future__ import annotations

from collections.abc import Callable

from app.services.analysis.rules.contracts import contract_for
from app.services.analysis.rules.enums import (
    AnalysisResultContract,
    AnalysisValidationCode,
)
from app.services.analysis.rules.errors import AnalysisValidationError
from app.services.analysis.rules.parse_helpers import ParseContext
from app.services.analysis.rules.result_drafts import (
    evidence_ids,
    parse_asset,
    parse_highlight,
    parse_production_advice,
    parse_scene,
    parse_shot,
)
from app.services.analysis.rules.result_items import Highlight, Shot, VisualAsset
from app.services.analysis.rules.result_models import (
    AnalysisLimits,
    AnalysisMedia,
    EvidenceSummary,
    VideoAnalysisResult,
    VideoArticleResult,
)
from app.services.analysis.rules.result_validation import validate_analysis_result
from app.services.analysis.rules.video_article_parser import parse_video_article_result
from app.services.analysis.rules.video_scene import VideoScene


def parse_analysis_result(
    payload: object,
    media: AnalysisMedia,
    *,
    expected_language: str,
    result_contract: str = AnalysisResultContract.VIDEO_VISUAL_ANALYSIS.value,
    limits: AnalysisLimits | None = None,
) -> VideoAnalysisResult | VideoArticleResult:
    """Strictly parse a video contract's model output."""
    parser = _VIDEO_PARSERS.get(contract_for(result_contract).contract)
    if parser is None:
        raise ValueError(f"not a video result contract: {result_contract}")
    return parser(payload, media, expected_language=expected_language, limits=limits)


def parse_visual_analysis_result(
    payload: object,
    media: AnalysisMedia,
    *,
    expected_language: str,
    limits: AnalysisLimits | None = None,
) -> VideoAnalysisResult:
    context = ParseContext(limits or AnalysisLimits())
    root = context.mapping(
        payload,
        "result",
        {
            "language",
            "title",
            "summary",
            "shots",
            "scenes",
            "highlights",
            "assets",
            "production_advice",
        },
    )
    language = context.text(root["language"], "language", maximum=35)
    if language != expected_language:
        raise AnalysisValidationError(
            AnalysisValidationCode.INVALID_SCHEMA,
            "output language does not match the job",
        )

    shot_drafts = tuple(
        parse_shot(context, value, index)
        for index, value in enumerate(
            context.array(root["shots"], "shots", allow_empty=False)
        )
    )
    highlight_drafts = tuple(
        parse_highlight(context, value, index)
        for index, value in enumerate(
            context.array(root["highlights"], "highlights", allow_empty=True)
        )
    )
    scene_drafts = tuple(
        parse_scene(context, value, index)
        for index, value in enumerate(
            context.array(root["scenes"], "scenes", allow_empty=False)
        )
    )
    asset_drafts = tuple(
        parse_asset(context, value, index)
        for index, value in enumerate(
            context.array(root["assets"], "assets", allow_empty=True)
        )
    )
    shot_by_id = {shot.id: shot for shot in shot_drafts}
    assets = tuple(
        VisualAsset(
            id=item.id,
            type=item.type,
            label=item.label,
            description=item.description,
            first_seen_ms=_first_seen(item.evidence_shot_ids, shot_by_id),
            evidence_shot_ids=item.evidence_shot_ids,
        )
        for item in asset_drafts
    )
    shots = tuple(
        Shot(
            id=item.id,
            index=item.index,
            start_ms=item.start_ms,
            end_ms=item.end_ms,
            representative_frame_ms=item.representative_frame_ms,
            description=item.description,
            transition_in=item.transition_in,
            shot_size=item.shot_size,
            camera_motion=item.camera_motion,
            narrative_function=item.narrative_function,
            highlight_score=item.highlight_score,
            visual_tags=item.visual_tags,
            asset_ids=tuple(
                asset.id for asset in assets if item.id in asset.evidence_shot_ids
            ),
        )
        for item in shot_drafts
    )
    highlights = tuple(
        Highlight(
            id=item.id,
            title=item.title,
            description=item.description,
            score=item.score,
            reason=item.reason,
            start_ms=_first_seen(item.evidence_shot_ids, shot_by_id),
            end_ms=_last_seen(item.evidence_shot_ids, shot_by_id),
            evidence_shot_ids=item.evidence_shot_ids,
        )
        for item in highlight_drafts
    )
    scenes = tuple(
        VideoScene(
            id=item.id,
            index=item.index,
            title=item.title,
            start_ms=_first_seen(item.evidence_shot_ids, shot_by_id),
            end_ms=_last_seen(item.evidence_shot_ids, shot_by_id),
            location=item.location,
            description=item.description,
            narrative_function=item.narrative_function,
            visual_rules=item.visual_rules,
            continuity_risks=item.continuity_risks,
            evidence_shot_ids=item.evidence_shot_ids,
        )
        for item in scene_drafts
    )
    result = VideoAnalysisResult(
        language=language,
        title=context.text(root["title"], "title"),
        summary=_summary(context, root["summary"]),
        media=media,
        shot_count=len(shots),
        shots=shots,
        scenes=scenes,
        highlights=highlights,
        assets=assets,
        production_advice=parse_production_advice(context, root["production_advice"]),
    )
    validate_analysis_result(
        result,
        limits=context.limits,
        enforce_segmentation_review=True,
    )
    return result


def _summary(context: ParseContext, value: object) -> EvidenceSummary:
    source = context.mapping(value, "summary", {"text", "evidence_shot_ids"})
    return EvidenceSummary(
        text=context.text(source["text"], "summary.text"),
        evidence_shot_ids=evidence_ids(
            context, source["evidence_shot_ids"], "summary.evidence_shot_ids"
        ),
    )


def _first_seen(references: tuple[str, ...], shots: dict[str, Shot]) -> int:
    return min(_referenced(references, shots), key=lambda shot: shot.start_ms).start_ms


def _last_seen(references: tuple[str, ...], shots: dict[str, Shot]) -> int:
    return max(_referenced(references, shots), key=lambda shot: shot.end_ms).end_ms


def _referenced(
    references: tuple[str, ...], shots: dict[str, Shot]
) -> tuple[Shot, ...]:
    try:
        return tuple(shots[shot_id] for shot_id in references)
    except KeyError as exc:
        raise AnalysisValidationError(
            AnalysisValidationCode.INVALID_EVIDENCE,
            f"unknown evidence shot id: {exc.args[0]}",
        ) from exc


_VIDEO_PARSERS: dict[
    AnalysisResultContract, Callable[..., VideoAnalysisResult | VideoArticleResult]
] = {
    AnalysisResultContract.VIDEO_VISUAL_ANALYSIS: parse_visual_analysis_result,
    AnalysisResultContract.VIDEO_ARTICLE: parse_video_article_result,
}
