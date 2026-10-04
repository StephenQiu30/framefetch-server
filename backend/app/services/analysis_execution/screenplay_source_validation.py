"""Shared integrity boundary; analysis and rewrite retain distinct planners."""

from app.services.analysis_execution.errors import AnalysisArtifactError
from app.services.analysis_execution.models import ScreenplaySceneSource


def validate_screenplay_source(
    text: str, scenes: tuple[ScreenplaySceneSource, ...]
) -> None:
    if (
        not text
        or "\r" in text
        or "\x00" in text
        or not scenes
        or len({scene.id for scene in scenes}) != len(scenes)
        or scenes[0].start != 0
        or scenes[-1].end != len(text)
    ):
        raise AnalysisArtifactError("artifact_integrity_failed")
    for index, scene in enumerate(scenes):
        if not 0 <= scene.start < scene.end <= len(text):
            raise AnalysisArtifactError("artifact_integrity_failed")
        if index > 0 and scenes[index - 1].end != scene.start:
            raise AnalysisArtifactError("artifact_integrity_failed")
