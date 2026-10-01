from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self

from app.services.downloads.rules.enums import (
    AudioCodecFamily,
    CompatibilityProfile,
    Container,
    ContainerPreference,
    DynamicRange,
    FpsBucket,
    MediaKind,
    StreamKind,
    VideoCodecFamily,
)
from app.services.downloads.rules.formats import (
    CandidateStream,
    DownloadPlan,
    ProviderHints,
)
from app.services.provider_failures import (
    FailureClass,
    FailureEvidenceKind,
    FailurePhase,
    FailureScope,
    ProviderFailure,
)
from app.services.provider_types import ExecutionContext
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeResponse(ContractModel):
    instance_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class ProviderFailureContract(ContractModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    phase: FailurePhase
    scope: FailureScope
    failure_class: FailureClass
    evidence_kind: FailureEvidenceKind
    observed_at: AwareDatetime
    retry_after: AwareDatetime | None = None
    diagnostic_ref: str | None = Field(default=None, max_length=128)
    cause_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    layer: str = Field(default="L1", pattern=r"^L[123]$")
    stage: str = Field(
        default="resolve", pattern=r"^(resolve|download|validate|publish)$"
    )
    summary: str = Field(default="", max_length=256)
    gate: Literal["①", "②", "③", "none"] = "none"
    evidence: dict[str, str | int | bool | None] = Field(default_factory=dict)

    def to_domain(self) -> ProviderFailure:
        return ProviderFailure(**self.model_dump())

    @classmethod
    def from_domain(cls, failure: ProviderFailure) -> Self:
        return cls(**asdict(failure))


class RunnerErrorContract(ContractModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    message: str = Field(max_length=256)
    failure: ProviderFailureContract

    @model_validator(mode="after")
    def _matching_code(self) -> Self:
        if self.code != self.failure.code:
            raise ValueError("runner error code does not match failure facts")
        self.failure.to_domain()
        return self


class ProviderHintsContract(ContractModel):
    video_id: str | None = Field(default=None, max_length=128)
    audio_id: str | None = Field(default=None, max_length=128)


class ExecutionContextContract(ContractModel):
    provider_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    resolved_layer: str = Field(pattern=r"^L[123]$")
    egress_route: str = Field(min_length=1, max_length=128)
    client: str = Field(min_length=1, max_length=128)
    registry_revision: str = Field(min_length=1, max_length=128)
    egress_revision: str = Field(min_length=1, max_length=128)
    egress_class: Literal["unknown", "residential", "datacenter"]
    egress_observed_ip: str | None
    identity_digest: str | None
    browser_context_kind: Literal["none", "anonymous", "authenticated"]
    identity_used: bool
    engine_revision: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def _valid_context(self) -> Self:
        self.to_domain()
        return self

    def to_domain(self) -> ExecutionContext:
        return ExecutionContext.from_document(self.model_dump())

    @classmethod
    def from_domain(cls, value: ExecutionContext) -> Self:
        return cls.model_validate(value.to_document())


class DownloadPlanContract(ContractModel):
    height: int = Field(gt=0, le=16_384)
    width: int = Field(gt=0, le=16_384)
    fps_bucket: FpsBucket
    dynamic_range: DynamicRange
    video_codec_family: VideoCodecFamily
    audio_codec_family: AudioCodecFamily
    audio_language: str | None = Field(default=None, max_length=64)
    container_preference: ContainerPreference
    compatibility_profile: CompatibilityProfile
    hints: ProviderHintsContract = Field(default_factory=ProviderHintsContract)

    def to_domain(self) -> DownloadPlan:
        return DownloadPlan(
            height=self.height,
            width=self.width,
            fps_bucket=self.fps_bucket,
            dynamic_range=self.dynamic_range,
            video_codec_family=self.video_codec_family,
            audio_codec_family=self.audio_codec_family,
            audio_language=self.audio_language,
            container_preference=self.container_preference,
            compatibility_profile=self.compatibility_profile,
            hints=ProviderHints(**self.hints.model_dump()),
        )

    @classmethod
    def from_domain(cls, plan: DownloadPlan) -> Self:
        return cls(
            height=plan.height,
            width=plan.width,
            fps_bucket=plan.fps_bucket,
            dynamic_range=plan.dynamic_range,
            video_codec_family=plan.video_codec_family,
            audio_codec_family=plan.audio_codec_family,
            audio_language=plan.audio_language,
            container_preference=plan.container_preference,
            compatibility_profile=plan.compatibility_profile,
            hints=ProviderHintsContract(
                video_id=plan.hints.video_id,
                audio_id=plan.hints.audio_id,
            ),
        )


class CandidateStreamContract(ContractModel):
    provider_id: str
    kind: StreamKind
    container: Container
    height: int | None = None
    width: int | None = None
    fps: float | None = None
    dynamic_range: DynamicRange | None = None
    video_codec_family: VideoCodecFamily | None = None
    audio_codec_family: AudioCodecFamily | None = None
    audio_language: str | None = None
    bitrate_kbps: int | None = None
    size_bytes: int | None = None

    @classmethod
    def from_domain(cls, stream: CandidateStream) -> Self:
        return cls(**{name: getattr(stream, name) for name in cls.model_fields})


class MediaSummary(ContractModel):
    provider_media_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=4096)
    duration_seconds: float = Field(ge=0)
    extractor_key: str = Field(min_length=1, max_length=128)
    thumbnail_data_url: str | None = Field(default=None, max_length=2_100_000)
    media_kind: MediaKind = MediaKind.VIDEO
    asset_count: int = Field(default=0, ge=0, le=1000)


class DownloadOption(ContractModel):
    option_id: str
    label: str
    plan: DownloadPlanContract | None = None
    media_kind: MediaKind = MediaKind.VIDEO
    asset_count: int = Field(default=0, ge=0, le=1000)


class InspectRequest(ContractModel):
    deadline: AwareDatetime
    issued_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    cleanup_token: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    task_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    url: str = Field(min_length=1, max_length=4096)
    execution_context: ExecutionContextContract | None = None


class InspectResponse(ContractModel):
    media: MediaSummary
    streams: list[CandidateStreamContract]
    options: list[DownloadOption]
    execution_context: ExecutionContextContract


class DownloadRequest(ContractModel):
    deadline: AwareDatetime | None = None
    issued_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    cleanup_token: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    task_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    url: str = Field(min_length=1, max_length=4096)
    expected_provider_media_id: str = Field(min_length=1, max_length=256)
    expected_extractor_key: str = Field(min_length=1, max_length=128)
    plan: DownloadPlanContract | None = None
    media_kind: MediaKind = MediaKind.VIDEO
    asset_count: int = Field(default=0, ge=0, le=1000)
    execution_context: ExecutionContextContract

    @model_validator(mode="after")
    def validate_media_plan(self) -> DownloadRequest:
        if self.media_kind is MediaKind.VIDEO and self.plan is None:
            raise ValueError("video downloads require a plan")
        if self.media_kind in {
            MediaKind.IMAGE_GALLERY,
            MediaKind.VIDEO_COLLECTION,
        }:
            if self.plan is not None:
                raise ValueError("media collections do not accept a video plan")
            if self.asset_count < 1:
                raise ValueError("media collections require an asset count")
        elif self.asset_count != 0:
            raise ValueError("single videos do not accept an asset count")
        return self

    @field_validator("expected_provider_media_id", "expected_extractor_key")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        has_control = any(
            ord(character) < 32 or ord(character) == 127 for character in value
        )
        if value != value.strip() or has_control:
            raise ValueError("expected media identity is invalid")
        return value


class ArtifactContract(ContractModel):
    relative_path: str
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration_seconds: float = Field(ge=0)
    container: Container
    video_streams: int = Field(ge=0)
    audio_streams: int = Field(ge=0)
    media_kind: MediaKind = MediaKind.VIDEO
    asset_count: int = Field(default=0, ge=0, le=1000)


class SelectedStreamsContract(ContractModel):
    video_provider_id: str
    audio_provider_id: str | None
    output_container: Container


class DownloadResponse(ContractModel):
    task_id: str
    workspace_path: str
    artifact: ArtifactContract
    selection: SelectedStreamsContract | None = None


class CancelCommand(ContractModel):
    pass


class CancelResponse(ContractModel):
    cleanup_token: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    task_id: str
    status: str = "stopped"


class RunnerTaskStage(StrEnum):
    REVALIDATING = "revalidating"
    DOWNLOADING = "downloading"
    REMUXING = "remuxing"
    VERIFYING = "verifying"
    READY = "ready"


class TaskStatusResponse(ContractModel):
    task_id: str
    stage: RunnerTaskStage
    progress: int = Field(ge=0, le=100)
