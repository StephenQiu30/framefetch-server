from __future__ import annotations

import pytest
from app.services.downloads.rules.enums import (
    AudioCodecFamily,
    CompatibilityProfile,
    Container,
    ContainerPreference,
    DownloadErrorCode,
    DynamicRange,
    FpsBucket,
    StreamKind,
    VideoCodecFamily,
)
from app.services.downloads.rules.errors import FormatSelectionError
from app.services.downloads.rules.formats import (
    CandidateStream,
    DownloadPlan,
    ProviderHints,
)
from app.services.downloads.rules.selection import select_streams


def plan(**changes: object) -> DownloadPlan:
    values: dict[str, object] = {
        "height": 1080,
        "width": 1920,
        "fps_bucket": FpsBucket.FPS_30,
        "dynamic_range": DynamicRange.SDR,
        "video_codec_family": VideoCodecFamily.H264,
        "audio_codec_family": AudioCodecFamily.AAC,
        "audio_language": "zh-CN",
        "container_preference": ContainerPreference.MP4,
        "compatibility_profile": CompatibilityProfile.BALANCED,
    }
    values.update(changes)
    return DownloadPlan(**values)  # type: ignore[arg-type]


def muxed(provider_id: str, **changes: object) -> CandidateStream:
    values: dict[str, object] = {
        "provider_id": provider_id,
        "kind": StreamKind.MUXED,
        "container": Container.MP4,
        "height": 1080,
        "width": 1920,
        "fps": 29.97,
        "dynamic_range": DynamicRange.SDR,
        "video_codec_family": VideoCodecFamily.H264,
        "audio_codec_family": AudioCodecFamily.AAC,
        "audio_language": "zh-CN",
        "bitrate_kbps": 2_500,
        "size_bytes": 20_000_000,
    }
    values.update(changes)
    return CandidateStream(**values)  # type: ignore[arg-type]


def video(provider_id: str, **changes: object) -> CandidateStream:
    values: dict[str, object] = {
        "provider_id": provider_id,
        "kind": StreamKind.VIDEO,
        "container": Container.MP4,
        "height": 1080,
        "width": 1920,
        "fps": 29.97,
        "dynamic_range": DynamicRange.SDR,
        "video_codec_family": VideoCodecFamily.H264,
        "bitrate_kbps": 2_500,
        "size_bytes": 18_000_000,
    }
    values.update(changes)
    return CandidateStream(**values)


def audio(provider_id: str, **changes: object) -> CandidateStream:
    values: dict[str, object] = {
        "provider_id": provider_id,
        "kind": StreamKind.AUDIO,
        "container": Container.MP4,
        "audio_codec_family": AudioCodecFamily.AAC,
        "audio_language": "zh-CN",
        "bitrate_kbps": 128,
        "size_bytes": 2_000_000,
    }
    values.update(changes)
    return CandidateStream(**values)  # type: ignore[arg-type]


def test_valid_semantic_provider_hint_wins_between_muxed_candidates() -> None:
    wanted = plan(hints=ProviderHints(video_id="fresh"))

    selected = select_streams(wanted, [muxed("other"), muxed("fresh")])

    assert selected.video.provider_id == "fresh"
    assert selected.audio is None
    assert selected.output_container is Container.MP4
    assert selected.used_provider_hint is True


def test_stale_or_wrong_hint_is_replaced_by_semantic_match() -> None:
    wanted = plan(hints=ProviderHints(video_id="stale"))
    wrong = muxed("stale", height=720, width=1280)
    replacement = muxed("new-id")

    selected = select_streams(wanted, [wrong, replacement])

    assert selected.video.provider_id == "new-id"
    assert selected.used_provider_hint is False


@pytest.mark.parametrize("clean_signal", [False, None])
def test_watermarked_hint_does_not_override_better_source(
    clean_signal: bool | None,
) -> None:
    selected = select_streams(
        plan(hints=ProviderHints(video_id="marked")),
        [
            muxed("marked", has_watermark=True),
            muxed("play", has_watermark=clean_signal),
        ],
    )
    assert selected.video.provider_id == "play"
    assert selected.used_provider_hint is False


def test_known_clean_split_is_preferred_over_watermarked_muxed() -> None:
    selected = select_streams(
        plan(),
        [
            muxed("marked", has_watermark=True),
            video("clean", has_watermark=False),
            audio("a"),
        ],
    )
    assert selected.video.provider_id == "clean"
    assert selected.audio is not None
    assert selected.audio.provider_id == "a"


def test_clean_source_does_not_downgrade_requested_quality() -> None:
    selected = select_streams(
        plan(),
        [
            muxed("marked", has_watermark=True),
            muxed("clean", has_watermark=False, height=720, width=1280),
        ],
    )
    assert selected.video.provider_id == "marked"


def test_known_clean_source_is_preferred_to_unknown_source() -> None:
    selected = select_streams(
        plan(hints=ProviderHints(video_id="unknown")),
        [muxed("unknown"), muxed("clean", has_watermark=False)],
    )
    assert selected.video.provider_id == "clean"


def test_selector_never_silently_downgrades_resolution() -> None:
    with pytest.raises(FormatSelectionError) as caught:
        select_streams(plan(), [muxed("720p", height=720, width=1280)])

    assert caught.value.code is DownloadErrorCode.FORMAT_UNAVAILABLE


def test_selector_accepts_small_same_aspect_provider_dimension_drift() -> None:
    wanted = plan(height=960, width=540)

    selected = select_streams(wanted, [muxed("fresh", height=1024, width=576)])

    assert selected.video.provider_id == "fresh"


def test_muxed_stream_is_preferred_over_compatible_split_streams() -> None:
    selected = select_streams(
        plan(),
        [video("v"), audio("a"), muxed("single", bitrate_kbps=1_000)],
    )

    assert selected.video.provider_id == "single"
    assert selected.audio is None


def test_compatible_split_streams_are_selected() -> None:
    wanted = plan(hints=ProviderHints(video_id="v", audio_id="a"))

    selected = select_streams(wanted, [audio("a"), video("v")])

    assert selected.video.provider_id == "v"
    assert selected.audio is not None
    assert selected.audio.provider_id == "a"
    assert selected.used_provider_hint is True


def test_silent_video_is_selected_without_an_audio_stream() -> None:
    wanted = plan(
        audio_codec_family=AudioCodecFamily.NONE,
        audio_language=None,
        hints=ProviderHints(video_id="silent"),
    )

    selected = select_streams(wanted, [video("silent")])

    assert selected.video.provider_id == "silent"
    assert selected.audio is None
    assert selected.output_container is Container.MP4
    assert selected.used_provider_hint is True


@pytest.mark.parametrize(
    ("container", "video_codec", "audio_codec"),
    [
        (ContainerPreference.MP4, VideoCodecFamily.VP9, AudioCodecFamily.OPUS),
        (ContainerPreference.WEBM, VideoCodecFamily.H264, AudioCodecFamily.AAC),
    ],
)
def test_incompatible_output_requires_transcoding(
    container: ContainerPreference,
    video_codec: VideoCodecFamily,
    audio_codec: AudioCodecFamily,
) -> None:
    wanted = plan(
        container_preference=container,
        video_codec_family=video_codec,
        audio_codec_family=audio_codec,
    )
    candidate = muxed(
        "exact",
        video_codec_family=video_codec,
        audio_codec_family=audio_codec,
    )

    with pytest.raises(FormatSelectionError) as caught:
        select_streams(wanted, [candidate])

    assert caught.value.code is DownloadErrorCode.TRANSCODE_REQUIRED


def test_profile_ranking_is_deterministic() -> None:
    candidates = [
        muxed("middle", size_bytes=20, bitrate_kbps=2_000),
        muxed("large", size_bytes=30, bitrate_kbps=3_000),
        muxed("small", size_bytes=10, bitrate_kbps=1_000),
    ]

    quality = select_streams(
        plan(compatibility_profile=CompatibilityProfile.QUALITY), candidates
    )
    smallest = select_streams(
        plan(compatibility_profile=CompatibilityProfile.SMALLEST), candidates
    )

    assert quality.video.provider_id == "large"
    assert smallest.video.provider_id == "small"


def test_fps_bucket_preserves_fractional_provider_values() -> None:
    assert FpsBucket.from_fps(29.97) is FpsBucket.FPS_30
    assert FpsBucket.from_fps(59.94) is FpsBucket.FPS_60
    assert FpsBucket.from_fps(120) is FpsBucket.ABOVE_60
