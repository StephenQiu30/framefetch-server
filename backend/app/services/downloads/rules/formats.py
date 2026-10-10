from __future__ import annotations

from dataclasses import dataclass, field

from app.services.downloads.rules.enums import (
    AudioCodecFamily,
    CompatibilityProfile,
    Container,
    ContainerPreference,
    DynamicRange,
    FpsBucket,
    StreamKind,
    VideoCodecFamily,
)


def _language(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().replace("_", "-").casefold()
    if not normalized:
        raise ValueError("audio language cannot be blank")
    return normalized


@dataclass(frozen=True, slots=True)
class ProviderHints:
    video_id: str | None = None
    audio_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("video_id", "audio_id"):
            value = getattr(self, name)
            if value is not None:
                value = value.strip()
                if not value:
                    raise ValueError(f"{name} cannot be blank")
                object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class DownloadPlan:
    height: int
    width: int
    fps_bucket: FpsBucket
    dynamic_range: DynamicRange
    video_codec_family: VideoCodecFamily
    audio_codec_family: AudioCodecFamily
    audio_language: str | None
    container_preference: ContainerPreference
    compatibility_profile: CompatibilityProfile
    hints: ProviderHints = field(default_factory=ProviderHints)

    def __post_init__(self) -> None:
        if self.height <= 0 or self.width <= 0:
            raise ValueError("video dimensions must be positive")
        object.__setattr__(self, "audio_language", _language(self.audio_language))

    def matches_video(self, stream: CandidateStream) -> bool:
        return (
            stream.kind in {StreamKind.MUXED, StreamKind.VIDEO}
            and stream.height == self.height
            and stream.width == self.width
            and stream.fps is not None
            and FpsBucket.from_fps(stream.fps) is self.fps_bucket
            and stream.dynamic_range is self.dynamic_range
            and stream.video_codec_family is self.video_codec_family
        )

    def matches_audio(self, stream: CandidateStream) -> bool:
        if stream.kind not in {StreamKind.MUXED, StreamKind.AUDIO}:
            return False
        language_matches = (
            self.audio_language is None or stream.audio_language == self.audio_language
        )
        return stream.audio_codec_family is self.audio_codec_family and language_matches


@dataclass(frozen=True, slots=True)
class CandidateStream:
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
    # None means the provider made no usable claim, not watermark-free media.
    has_watermark: bool | None = None

    def __post_init__(self) -> None:
        provider_id = self.provider_id.strip()
        if not provider_id:
            raise ValueError("provider id cannot be blank")
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "audio_language", _language(self.audio_language))
        self._validate_metrics()
        if self.kind in {StreamKind.MUXED, StreamKind.VIDEO}:
            self._validate_video()
        if self.kind in {StreamKind.MUXED, StreamKind.AUDIO}:
            self._validate_audio()

    def _validate_metrics(self) -> None:
        if self.bitrate_kbps is not None and self.bitrate_kbps <= 0:
            raise ValueError("bitrate must be positive")
        if self.size_bytes is not None and self.size_bytes <= 0:
            raise ValueError("size must be positive")

    def _validate_video(self) -> None:
        if (
            self.height is None
            or self.width is None
            or self.fps is None
            or self.dynamic_range is None
            or self.video_codec_family is None
        ):
            raise ValueError("video stream metadata is incomplete")
        if self.height <= 0 or self.width <= 0:
            raise ValueError("video dimensions must be positive")
        FpsBucket.from_fps(self.fps)

    def _validate_audio(self) -> None:
        if self.audio_codec_family is None:
            raise ValueError("audio stream metadata is incomplete")


@dataclass(frozen=True, slots=True)
class StreamSelection:
    video: CandidateStream
    audio: CandidateStream | None
    output_container: Container
    used_provider_hint: bool


def download_plan_priority(
    plan: DownloadPlan,
) -> tuple[bool, int, int, str, str, str, str, int, str, str]:
    """One deterministic recommendation order for Runner and persisted results."""
    fps_rank = {FpsBucket.FPS_30: 0, FpsBucket.FPS_60: 1, FpsBucket.ABOVE_60: 2}
    return (
        plan.audio_codec_family is AudioCodecFamily.NONE,
        -plan.height,
        -plan.width,
        plan.container_preference.value,
        plan.video_codec_family.value,
        plan.audio_codec_family.value,
        plan.audio_language or "",
        -fps_rank[plan.fps_bucket],
        plan.dynamic_range.value,
        plan.compatibility_profile.value,
    )
