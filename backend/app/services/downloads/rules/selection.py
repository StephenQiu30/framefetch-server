from __future__ import annotations

from collections.abc import Iterable

from app.services.downloads.rules.enums import (
    AudioCodecFamily,
    CompatibilityProfile,
    Container,
    ContainerPreference,
    DownloadErrorCode,
    FpsBucket,
    StreamKind,
    VideoCodecFamily,
)
from app.services.downloads.rules.errors import FormatSelectionError
from app.services.downloads.rules.formats import (
    CandidateStream,
    DownloadPlan,
    StreamSelection,
)

_COMPATIBLE_CODECS = {
    Container.MP4: (
        {VideoCodecFamily.H264, VideoCodecFamily.HEVC},
        {AudioCodecFamily.NONE, AudioCodecFamily.AAC},
    ),
    Container.WEBM: (
        {VideoCodecFamily.VP9, VideoCodecFamily.AV1},
        {
            AudioCodecFamily.NONE,
            AudioCodecFamily.OPUS,
            AudioCodecFamily.VORBIS,
        },
    ),
}


def select_streams(
    plan: DownloadPlan, streams: Iterable[CandidateStream]
) -> StreamSelection:
    available = tuple(streams)
    muxed = [
        stream
        for stream in available
        if stream.kind is StreamKind.MUXED
        and _matches_video(plan, stream)
        and plan.matches_audio(stream)
    ]
    videos = [
        stream
        for stream in available
        if stream.kind is StreamKind.VIDEO and _matches_video(plan, stream)
    ]
    audios = [
        stream
        for stream in available
        if stream.kind is StreamKind.AUDIO and plan.matches_audio(stream)
    ]
    candidates: list[tuple[CandidateStream, CandidateStream | None]] = [
        (stream, None) for stream in muxed
    ]
    if plan.audio_codec_family is AudioCodecFamily.NONE:
        candidates.extend((stream, None) for stream in videos)
    candidates.extend((video, audio) for video in videos for audio in audios)
    selections = [
        StreamSelection(
            video=video,
            audio=audio,
            output_container=output,
            used_provider_hint=_used_hints(plan, video, audio),
        )
        for video, audio in candidates
        if (output := _output_for(plan, video, audio)) is not None
    ]
    if selections:
        # Compare watermark evidence before the muxed preference or stale hints.
        # Equal evidence retains the existing muxed-first selection semantics.
        return min(
            selections,
            key=lambda item: (
                _watermark_rank(item.video),
                item.video.kind is not StreamKind.MUXED,
                _rank(plan, item.video, "video"),
                _rank(plan, item.audio, "audio") if item.audio is not None else (),
            ),
        )
    if candidates:
        raise FormatSelectionError(DownloadErrorCode.TRANSCODE_REQUIRED)
    raise FormatSelectionError(DownloadErrorCode.FORMAT_UNAVAILABLE)


def _watermark_rank(stream: CandidateStream) -> int:
    if stream.has_watermark is False:
        return 0
    return 2 if stream.has_watermark is True else 1


def _matches_video(plan: DownloadPlan, stream: CandidateStream) -> bool:
    if plan.matches_video(stream):
        return True
    if (
        stream.kind not in {StreamKind.MUXED, StreamKind.VIDEO}
        or stream.height is None
        or stream.width is None
        or stream.fps is None
        or stream.dynamic_range is not plan.dynamic_range
        or stream.video_codec_family is not plan.video_codec_family
        or FpsBucket.from_fps(stream.fps) is not plan.fps_bucket
    ):
        return False

    # Some providers (notably TikTok) rotate CDN renditions between requests,
    # changing the encoded pixel dimensions by a few percent while retaining
    # the same quality tier. Accept only a close, same-aspect-ratio rendition;
    # a real resolution downgrade remains unavailable.
    target_ratio = plan.width / plan.height
    stream_ratio = stream.width / stream.height
    ratio_delta = abs(stream_ratio - target_ratio) / target_ratio
    width_delta = abs(stream.width - plan.width) / plan.width
    height_delta = abs(stream.height - plan.height) / plan.height
    return ratio_delta <= 0.02 and width_delta <= 0.12 and height_delta <= 0.12


def _output_for(
    plan: DownloadPlan,
    video: CandidateStream,
    audio: CandidateStream | None,
) -> Container | None:
    if plan.container_preference is ContainerPreference.MP4:
        choices: tuple[Container, ...] = (Container.MP4,)
    elif plan.container_preference is ContainerPreference.WEBM:
        choices = (Container.WEBM,)
    elif audio is None:
        choices = (video.container,)
    else:
        choices = (video.container, audio.container)
    for container in choices:
        allowed = _COMPATIBLE_CODECS.get(container)
        if allowed is None:
            continue
        video_codecs, audio_codecs = allowed
        if (
            plan.video_codec_family in video_codecs
            and plan.audio_codec_family in audio_codecs
        ):
            return container
    return None


def _rank(
    plan: DownloadPlan, stream: CandidateStream, role: str
) -> tuple[int, int, int, str]:
    hint = plan.hints.video_id if role == "video" else plan.hints.audio_id
    hint_rank = 0 if hint is not None and stream.provider_id == hint else 1
    bitrate = stream.bitrate_kbps or 0
    size = stream.size_bytes if stream.size_bytes is not None else 2**63 - 1
    if plan.compatibility_profile is CompatibilityProfile.QUALITY:
        return hint_rank, -bitrate, -size, stream.provider_id
    if plan.compatibility_profile is CompatibilityProfile.SMALLEST:
        return hint_rank, size, bitrate, stream.provider_id
    return hint_rank, -bitrate, size, stream.provider_id


def _used_hints(
    plan: DownloadPlan,
    video: CandidateStream,
    audio: CandidateStream | None,
) -> bool:
    expected = [plan.hints.video_id, plan.hints.audio_id]
    selected = [video.provider_id, audio.provider_id if audio is not None else None]
    present = [
        (hint, actual) for hint, actual in zip(expected, selected, strict=True) if hint
    ]
    return bool(present) and all(hint == actual for hint, actual in present)
