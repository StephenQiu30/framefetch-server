from __future__ import annotations

import re
from dataclasses import asdict
from enum import StrEnum
from typing import Self

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
from app.services.provider_types import ProviderAccessContextRef, ProviderAccessMode
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
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
    strategy_id: str | None = Field(default=None, max_length=128)
    context_key: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    retry_after: AwareDatetime | None = None
    diagnostic_ref: str | None = Field(default=None, max_length=128)
    cause_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")

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


class ProviderAccessContextContract(ContractModel):
    provider_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    profile_version: str = Field(min_length=1, max_length=128)
    access_mode: ProviderAccessMode
    credential_version_id: str | None = Field(default=None, max_length=128)
    egress_affinity_id: str = Field(min_length=1, max_length=128)
    client_profile_id: str = Field(min_length=1, max_length=128)
    attestation_provider_version: str | None = Field(default=None, max_length=128)
    engine_commit: str = Field(min_length=1, max_length=128)
    runtime_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    strategy_id: str | None = Field(default=None, max_length=128)
    adapter_revision: str | None = Field(default=None, max_length=128)
    session_source_id: str | None = Field(default=None, max_length=128)
    browser_context_revision: str | None = Field(default=None, max_length=128)
    protocol_capabilities: tuple[str, ...] = Field(default=(), max_length=32)
    egress_observation_ref: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _valid_context(self) -> Self:
        self.to_domain()
        return self

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        document: dict[str, object] = handler(self)
        if self.runtime_revision is None:
            document.pop("runtime_revision", None)
        if self.strategy_id is None:
            for name in (
                "strategy_id",
                "adapter_revision",
                "session_source_id",
                "browser_context_revision",
                "protocol_capabilities",
                "egress_observation_ref",
            ):
                document.pop(name, None)
        return document

    def to_domain(self) -> ProviderAccessContextRef:
        return ProviderAccessContextRef(
            provider_key=self.provider_key,
            profile_version=self.profile_version,
            access_mode=self.access_mode,
            credential_version_id=self.credential_version_id,
            egress_affinity_id=self.egress_affinity_id,
            client_profile_id=self.client_profile_id,
            attestation_provider_version=self.attestation_provider_version,
            engine_commit=self.engine_commit,
            runtime_revision=self.runtime_revision or "legacy",
            strategy_id=self.strategy_id,
            adapter_revision=self.adapter_revision,
            session_source_id=self.session_source_id,
            browser_context_revision=self.browser_context_revision,
            protocol_capabilities=self.protocol_capabilities,
            egress_observation_ref=self.egress_observation_ref,
        )

    @classmethod
    def from_domain(cls, value: ProviderAccessContextRef) -> Self:
        return cls(
            provider_key=value.provider_key,
            profile_version=value.profile_version,
            access_mode=value.access_mode,
            credential_version_id=value.credential_version_id,
            egress_affinity_id=value.egress_affinity_id,
            client_profile_id=value.client_profile_id,
            attestation_provider_version=value.attestation_provider_version,
            engine_commit=value.engine_commit,
            runtime_revision=(
                None if value.runtime_revision == "legacy" else value.runtime_revision
            ),
            strategy_id=value.strategy_id,
            adapter_revision=value.adapter_revision,
            session_source_id=value.session_source_id,
            browser_context_revision=value.browser_context_revision,
            protocol_capabilities=value.protocol_capabilities,
            egress_observation_ref=value.egress_observation_ref,
        )


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
    strategy_id: str = Field(min_length=1, max_length=128)
    plan_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    operation_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    url: str = Field(min_length=1, max_length=4096)
    access_context: ProviderAccessContextContract
    deadline_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _selected_strategy(self) -> Self:
        if self.access_context.strategy_id != self.strategy_id:
            raise ValueError("inspection strategy differs from context")
        if self.operation_id is not None and self.deadline_at is None:
            raise ValueError("durable inspection requires a deadline")
        return self


class InspectionOperationResponse(ContractModel):
    status: str = Field(
        pattern=r"^(active|succeeded|failed|cancelled|outcome_unknown)$"
    )
    result: InspectResponse | None = None
    failure: ProviderFailureContract | None = None

    @model_validator(mode="after")
    def _receipt(self) -> Self:
        if (self.status == "succeeded") != (self.result is not None):
            raise ValueError("inspection receipt result mismatch")
        if self.status in {"failed", "cancelled"} and self.failure is None:
            raise ValueError("inspection failure receipt missing")
        return self


class ProviderContextRequest(ContractModel):
    access_mode: ProviderAccessMode | None = None
    strategy_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
    )
    plan_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    # The URL, not the provider key: a site session is keyed by the URL's site.
    url: str = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def _selected_route(self) -> Self:
        if (self.strategy_id is None) != (self.plan_revision is None):
            raise ValueError("selected context requires its plan revision")
        return self


class ProviderContextsRequest(ContractModel):
    access_mode: ProviderAccessMode | None = None
    provider_keys: list[str] = Field(min_length=1, max_length=64)

    @field_validator("provider_keys")
    @classmethod
    def validate_provider_keys(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(
            re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", key) is None for key in value
        ):
            raise ValueError("provider keys are invalid")
        return value


class ProviderContextsResponse(ContractModel):
    contexts: list[ProviderAccessContextContract]


class InspectResponse(ContractModel):
    media: MediaSummary
    streams: list[CandidateStreamContract]
    options: list[DownloadOption]
    access_context: ProviderAccessContextContract


class DownloadRequest(ContractModel):
    task_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    url: str = Field(min_length=1, max_length=4096)
    expected_provider_media_id: str = Field(min_length=1, max_length=256)
    expected_extractor_key: str = Field(min_length=1, max_length=128)
    plan: DownloadPlanContract | None = None
    media_kind: MediaKind = MediaKind.VIDEO
    asset_count: int = Field(default=0, ge=0, le=1000)
    access_context: ProviderAccessContextContract

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
