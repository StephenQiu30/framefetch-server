from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from app.services.analysis.models import AnalysisReportArtifactSnapshot
from app.services.analysis.rules.enums import AnalysisResultContract
from app.services.analysis.rules.result_types import AnalysisResult

SCREENPLAY_SINGLE_CALL_SCENE_LIMIT = 120
SCREENPLAY_SYNTHESIS_SCENE_LIMIT = 5_000


class AnalysisStepStatus(StrEnum):
    NEW = "new"
    REPLAY = "replay"
    UNKNOWN = "unknown"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AnalysisStepBegin:
    status: AnalysisStepStatus
    payload: object | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class AnalysisExecutionSettings:
    bucket: str
    lease_for: timedelta
    heartbeat_interval: float
    max_source_bytes: int
    provider: str = "controlled"
    model: str = "controlled"
    cli_version: str = "controlled"

    def __post_init__(self) -> None:
        if (
            not self.bucket.strip()
            or not self.provider.strip()
            or not self.model.strip()
            or not self.cli_version.strip()
        ):
            raise ValueError("bucket and provider labels cannot be blank")
        if self.lease_for.total_seconds() <= 0 or self.heartbeat_interval <= 0:
            raise ValueError("lease and heartbeat interval must be positive")
        if self.heartbeat_interval >= self.lease_for.total_seconds():
            raise ValueError("heartbeat interval must be shorter than the lease")
        if self.max_source_bytes <= 0:
            raise ValueError("source byte limit must be positive")


@dataclass(frozen=True, slots=True)
class AnalysisArtifactSource:
    artifact_id: UUID
    bucket: str
    object_key: str
    sha256: str
    size_bytes: int
    duration_ms: int
    container: str


@dataclass(frozen=True, slots=True)
class ScreenplaySceneSource:
    id: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if (
            not self.id.startswith(("scene-", "unit-"))
            or len(self.id) > 128
            or isinstance(self.start, bool)
            or isinstance(self.end, bool)
            or not 0 <= self.start < self.end
        ):
            raise ValueError("invalid screenplay scene source")


@dataclass(frozen=True, slots=True)
class AnalysisScreenplaySource:
    artifact_id: UUID
    document_id: UUID
    owner_hash: str
    bucket: str
    object_key: str
    sha256: str
    size_bytes: int
    character_count: int
    detected_language: str
    scenes: tuple[ScreenplaySceneSource, ...]

    def __post_init__(self) -> None:
        if (
            self.size_bytes <= 0
            or self.character_count <= 0
            or not self.bucket.strip()
            or not self.object_key.strip()
            or len(self.sha256) != 64
            or len(self.owner_hash) != 64
            or self.detected_language not in {"zh-CN", "en-US", "mixed", "unknown"}
            or not 0 <= len(self.scenes) <= 5_000
        ):
            raise ValueError("invalid screenplay analysis source")
        previous_end = 0
        for scene in self.scenes:
            if scene.start < previous_end or scene.end > self.character_count:
                raise ValueError("screenplay scene ranges must be ordered and bounded")
            previous_end = scene.end


@dataclass(frozen=True, slots=True)
class LocalAnalysisArtifact:
    workspace: Path
    artifact: Path


@dataclass(frozen=True, slots=True)
class LocalScreenplayArtifact:
    workspace: Path
    screenplay: Path


@dataclass(frozen=True, slots=True)
class VideoAnalysisRequest:
    artifact: Path
    workspace: Path
    duration_ms: int
    size_bytes: int
    container: str
    output_language: str
    skill_id: str
    skill_instructions: str
    result_contract: AnalysisResultContract = (
        AnalysisResultContract.VIDEO_VISUAL_ANALYSIS
    )
    custom_prompt: str | None = None
    stage: str = "draft"
    stage_prompt: str | None = field(default=None, repr=False)
    schema_json: str | None = field(default=None, repr=False)
    observation_ms: tuple[int, ...] = ()
    image_paths: tuple[Path, ...] = ()
    image_digests: tuple[str, ...] = ()
    measured_context: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.duration_ms <= 0 or self.size_bytes <= 0:
            raise ValueError("video analysis media values must be positive")
        labels = (
            self.container,
            self.output_language,
            self.skill_id,
            self.skill_instructions,
        )
        if any(not value.strip() for value in labels):
            raise ValueError("video analysis labels cannot be blank")
        if self.custom_prompt is not None and (
            not self.custom_prompt.strip() or len(self.custom_prompt) > 4_000
        ):
            raise ValueError("custom prompt must be non-blank and at most 4000 chars")


@dataclass(frozen=True, slots=True)
class ScreenplayAnalysisRequest:
    screenplay: Path
    workspace: Path
    screenplay_text: str = field(repr=False)
    source_scene_ids: tuple[str, ...]
    source_language: str
    output_language: str
    skill_id: str
    skill_instructions: str
    custom_prompt: str | None = None
    source_index_json: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if (
            not self.screenplay_text
            or self.source_language not in {"zh-CN", "en-US", "mixed", "unknown"}
            or self.output_language not in {"zh-CN", "en-US"}
            or not self.source_scene_ids
            or len(self.source_scene_ids) > SCREENPLAY_SINGLE_CALL_SCENE_LIMIT
            or len(set(self.source_scene_ids)) != len(self.source_scene_ids)
        ):
            raise ValueError("screenplay analysis request is invalid")
        if any(not value.strip() for value in (self.skill_id, self.skill_instructions)):
            raise ValueError("screenplay analysis labels cannot be blank")
        if self.custom_prompt is not None and (
            not self.custom_prompt.strip() or len(self.custom_prompt) > 4_000
        ):
            raise ValueError("custom prompt must be non-blank and at most 4000 chars")


@dataclass(frozen=True, slots=True)
class ScreenplayAnalysisSynthesisRequest:
    screenplay: Path
    workspace: Path
    chunk_results_json: str = field(repr=False)
    source_scene_ids: tuple[str, ...]
    source_language: str
    output_language: str
    skill_id: str
    skill_instructions: str
    custom_prompt: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.chunk_results_json
            or self.source_language not in {"zh-CN", "en-US", "mixed", "unknown"}
            or self.output_language not in {"zh-CN", "en-US"}
            or not self.source_scene_ids
            or len(self.source_scene_ids) > SCREENPLAY_SYNTHESIS_SCENE_LIMIT
            or len(set(self.source_scene_ids)) != len(self.source_scene_ids)
        ):
            raise ValueError("screenplay analysis synthesis request is invalid")
        if any(not value.strip() for value in (self.skill_id, self.skill_instructions)):
            raise ValueError("screenplay analysis labels cannot be blank")
        if self.custom_prompt is not None and (
            not self.custom_prompt.strip() or len(self.custom_prompt) > 4_000
        ):
            raise ValueError("custom prompt must be non-blank and at most 4000 chars")


@dataclass(frozen=True, slots=True)
class AnalysisExecutionOutput:
    result: AnalysisResult
    provider: str
    model: str
    cli_version: str
    native_markdown: str | None = field(default=None, repr=False)
    native_artifacts: tuple[AnalysisReportArtifactSnapshot, ...] = ()
    native_bucket: str | None = None

    def __post_init__(self) -> None:
        if any(
            not value.strip() for value in (self.provider, self.model, self.cli_version)
        ):
            raise ValueError("analysis execution provider labels cannot be blank")
