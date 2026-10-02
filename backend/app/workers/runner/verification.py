from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from app.services.downloads.rules.enums import (
    AudioCodecFamily,
    Container,
    DynamicRange,
    FpsBucket,
)
from app.services.downloads.rules.formats import DownloadPlan
from app.workers.runner.codecs import audio_codec_family, video_codec_family
from app.workers.runner.errors import RunnerFailure


@dataclass(frozen=True, slots=True)
class VerifiedProbe:
    duration_seconds: float
    video_streams: int
    audio_streams: int


@dataclass(frozen=True, slots=True)
class VerifiedCollectionVideo:
    duration_seconds: float
    video_streams: int
    audio_streams: int
    extension: str


def verify_collection_video(
    payload: dict[str, Any],
    *,
    max_duration: float,
    source_extension: str,
) -> VerifiedCollectionVideo:
    """Verify one downloaded collection member without imposing one format plan."""
    format_info = payload.get("format")
    streams = payload.get("streams")
    if not isinstance(format_info, dict) or not isinstance(streams, list):
        raise RunnerFailure("invalid_artifact", status=422)
    names = {
        name.strip().casefold()
        for name in str(format_info.get("format_name") or "").split(",")
    }
    if not names & {"mp4", "mov", "m4v", "3gp", "3g2", "webm", "matroska"}:
        raise RunnerFailure("invalid_artifact", status=422)
    video = [item for item in streams if _stream_type(item) == "video"]
    audio = [item for item in streams if _stream_type(item) == "audio"]
    if not video:
        raise RunnerFailure("invalid_artifact", status=422)
    duration = _duration(format_info.get("duration"))
    if duration is None or duration > max_duration:
        raise RunnerFailure("invalid_artifact", status=422)
    extension = _collection_extension(source_extension, names)
    return VerifiedCollectionVideo(duration, len(video), len(audio), extension)


def _collection_extension(source_extension: str, names: set[str]) -> str:
    extension = source_extension.casefold().lstrip(".")
    if extension in {"mp4", "webm", "mkv", "mov", "m4v", "3gp", "3g2"}:
        return extension
    return "webm" if "webm" in names and "mp4" not in names else "mp4"


def verify_probe(
    payload: dict[str, Any],
    *,
    plan: DownloadPlan,
    expected_container: Container,
    expected_duration: float,
    max_duration: float,
    tolerance_seconds: float,
) -> VerifiedProbe:
    format_info = payload.get("format")
    streams = payload.get("streams")
    if not isinstance(format_info, dict) or not isinstance(streams, list):
        raise RunnerFailure("invalid_artifact", status=422)
    if not _container_matches(format_info.get("format_name"), expected_container):
        raise RunnerFailure("invalid_artifact", status=422)

    video = [item for item in streams if _stream_type(item) == "video"]
    audio = [item for item in streams if _stream_type(item) == "audio"]
    if len(video) != 1:
        raise RunnerFailure("invalid_artifact", status=422)
    first_video = video[0]
    try:
        fps = float(Fraction(str(first_video.get("avg_frame_rate") or "0")))
        bucket = FpsBucket.from_fps(fps)
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise RunnerFailure("invalid_artifact", status=422) from exc
    if bucket is not plan.fps_bucket:
        raise RunnerFailure("invalid_artifact", status=422)
    dynamic_range = (
        DynamicRange.HDR
        if first_video.get("color_transfer") in {"smpte2084", "arib-std-b67"}
        else DynamicRange.SDR
    )
    if dynamic_range is not plan.dynamic_range:
        raise RunnerFailure("invalid_artifact", status=422)
    dimensions = (first_video.get("width"), first_video.get("height"))
    if dimensions != (plan.width, plan.height):
        raise RunnerFailure("invalid_artifact", status=422)
    if video_codec_family(first_video.get("codec_name")) is not plan.video_codec_family:
        raise RunnerFailure("invalid_artifact", status=422)
    if plan.audio_codec_family is AudioCodecFamily.NONE:
        if audio:
            raise RunnerFailure("invalid_artifact", status=422)
    else:
        if not audio:
            raise RunnerFailure("invalid_artifact", status=422)
        if (
            audio_codec_family(audio[0].get("codec_name"))
            is not plan.audio_codec_family
        ):
            raise RunnerFailure("invalid_artifact", status=422)

    duration = _duration(format_info.get("duration"))
    tolerance = max(tolerance_seconds, expected_duration * 0.02)
    if duration is None or duration > max_duration:
        raise RunnerFailure("invalid_artifact", status=422)
    if abs(duration - expected_duration) > tolerance:
        raise RunnerFailure("invalid_artifact", status=422)
    for stream in (*video, *audio):
        if "duration" not in stream:
            continue
        stream_duration = _duration(stream["duration"])
        if (
            stream_duration is None
            or stream_duration > max_duration
            or abs(stream_duration - expected_duration) > tolerance
        ):
            raise RunnerFailure("invalid_artifact", status=422)
    return VerifiedProbe(duration, len(video), len(audio))


def _stream_type(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    stream_type = value.get("codec_type")
    return stream_type if isinstance(stream_type, str) else None


def _container_matches(value: object, expected: Container) -> bool:
    names = {name.strip() for name in str(value or "").casefold().split(",")}
    if expected is Container.MP4:
        return bool(names & {"mp4", "mov", "m4a", "3gp", "3g2", "mj2"})
    if expected is Container.WEBM:
        return bool(names & {"webm", "matroska"})
    return False


def _duration(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        duration = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return duration if math.isfinite(duration) and duration > 0 else None
