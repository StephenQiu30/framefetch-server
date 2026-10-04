from __future__ import annotations

import json
from dataclasses import asdict

from app.services.analysis.models import AnalysisJobSnapshot
from app.services.analysis.rules.enums import AnalysisValidationCode
from app.services.analysis.rules.errors import AnalysisValidationError
from app.services.analysis.rules.screenplay_result_items import ScreenplayFinding
from app.services.analysis.rules.screenplay_results import ScreenplayAnalysisResult
from app.services.analysis_execution.errors import AnalysisArtifactError
from app.services.analysis_execution.models import (
    AnalysisScreenplaySource,
    LocalScreenplayArtifact,
    ScreenplayAnalysisRequest,
    ScreenplaySceneSource,
)


def build_analysis_request(
    job: AnalysisJobSnapshot,
    source: AnalysisScreenplaySource,
    local: LocalScreenplayArtifact,
    text: str,
    scenes: tuple[ScreenplaySceneSource, ...],
) -> ScreenplayAnalysisRequest:
    return ScreenplayAnalysisRequest(
        screenplay=local.screenplay,
        workspace=local.workspace,
        screenplay_text=text,
        source_scene_ids=tuple(scene.id for scene in scenes),
        source_language=source.detected_language,
        output_language=job.output_language,
        skill_id=job.skill_id,
        skill_instructions=job.skill_instructions,
        custom_prompt=job.custom_prompt,
        source_index_json=json.dumps(
            {
                "source_sha256": source.sha256,
                "offset_unit": "unicode_codepoints",
                "unit_kind": "scene"
                if scenes[0].id.startswith("scene-")
                else "text_unit",
                "units": [
                    {"id": scene.id, "start": scene.start, "end": scene.end}
                    for scene in scenes
                ],
            },
            ensure_ascii=False,
        ),
    )


def chunk_results_json(results: tuple[ScreenplayAnalysisResult, ...]) -> str:
    chunks: list[dict[str, object]] = []
    for result in results:
        document = asdict(result)
        document.pop("kind", None)
        chunks.append(document)
    return json.dumps({"chunks": chunks}, ensure_ascii=False, separators=(",", ":"))


def synthesis_results_json(
    results: tuple[ScreenplayAnalysisResult, ...], *, maximum_bytes: int
) -> str:
    """Keep full chunk results when they fit; bound the synthesis copy on overflow.

    The validated scene results remain untouched and are merged into the final
    report after synthesis. The compact copy preserves every source scene ID.
    """
    full = chunk_results_json(results)
    if len(full.encode()) <= maximum_bytes:
        return full
    chunks: list[dict[str, object]] = []
    for result in results:
        chunks.append(
            {
                "title": _brief(result.title, 160),
                "logline": _brief(result.logline, 600),
                "synopsis": _brief(result.synopsis, 1600),
                "pacing_summary": _brief(result.structure.pacing_summary, 600),
                "acts": _findings(result.structure.acts),
                "turning_points": _findings(result.structure.turning_points),
                "characters": [
                    {
                        "name": _brief(item.name, 120),
                        "goal": _brief(item.goal, 240),
                        "conflict": _brief(item.conflict, 240),
                        "arc": _brief(item.arc, 320),
                    }
                    for item in result.characters[:32]
                ],
                "dialogue_findings": _findings(result.dialogue_findings),
                "strengths": _findings(result.strengths),
                "priority_revisions": _findings(result.priority_revisions),
                "scenes": [
                    {
                        "source_scene_id": item.source_scene_id,
                        "purpose": _brief(item.purpose, 240),
                        "conflict": _brief(item.conflict, 240),
                        "turn": _brief(item.turn, 240),
                        "pacing": _brief(item.pacing, 160),
                        "findings": [
                            _brief(finding, 160) for finding in item.findings[:3]
                        ],
                    }
                    for item in result.scenes
                ],
            }
        )
    compact = json.dumps(
        {"projection_limited": True, "chunks": chunks},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(compact.encode()) > maximum_bytes:
        raise AnalysisArtifactError("analysis_resource_limit")
    return compact


def _findings(items: tuple[ScreenplayFinding, ...]) -> list[dict[str, object]]:
    return [
        {
            "title": _brief(item.title, 160),
            "description": _brief(item.description, 360),
        }
        for item in items[:32]
    ]


def _brief(value: str, maximum: int) -> str:
    return value if len(value) <= maximum else value[:maximum] + "…"


def combined_analysis_payload(
    summary: object, results: tuple[ScreenplayAnalysisResult, ...]
) -> dict[str, object]:
    if not isinstance(summary, dict) or "scenes" in summary:
        raise AnalysisValidationError(
            AnalysisValidationCode.INVALID_SCHEMA,
            "screenplay synthesis result is invalid",
        )
    scenes = [
        {
            "id": scene.source_scene_id,
            "source_scene_id": scene.source_scene_id,
            "purpose": scene.purpose,
            "conflict": scene.conflict,
            "turn": scene.turn,
            "pacing": scene.pacing,
            "findings": list(scene.findings),
        }
        for result in results
        for scene in result.scenes
    ]
    return {**summary, "scenes": scenes}
