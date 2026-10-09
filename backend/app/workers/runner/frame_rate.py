"""Frame-rate facts shared by candidate inspection and final validation."""

import math
from collections.abc import Mapping
from fractions import Fraction

from app.services.downloads.rules.enums import FpsBucket


def probe_frame_rate(
    video: Mapping[str, object], *, allow_nominal_fps: bool = False
) -> float | None:
    average = _positive_fraction(video.get("avg_frame_rate"))
    nominal = _positive_fraction(video.get("r_frame_rate"))
    if average is None:
        # Only a deliberately bounded codec-header probe can use its nominal
        # rate. A remote demuxer's timestamp base is not an observed average.
        width, height = video.get("width"), video.get("height")
        header_complete = (
            isinstance(video.get("codec_name"), str)
            and video.get("codec_name") not in {"", "unknown"}
            and type(width) is int
            and width > 0
            and type(height) is int
            and height > 0
        )
        return (
            float(nominal)
            if allow_nominal_fps and header_complete and nominal is not None
            else None
        )
    ticks = video.get("duration_ts")
    frames = _positive_fraction(video.get("nb_frames"))
    time_base = _positive_fraction(video.get("time_base"))
    if (
        nominal is not None
        and frames is not None
        and frames.denominator == 1
        and frames > 1
        and time_base is not None
        and type(ticks) is int
        and ticks > 0
    ):
        duration = ticks * time_base
        # Copy remuxing may shorten only the final sample. Require exact frame
        # accounting and a discrepancy strictly smaller than one nominal frame.
        if average * duration == frames and frames - 1 < nominal * duration <= frames:
            return float(nominal)
    return float(average)


def _positive_fraction(value: object) -> Fraction | None:
    if isinstance(value, bool):
        return None
    try:
        result = Fraction(str(value))
        return result if result > 0 and math.isfinite(float(result)) else None
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def needs_local_frame_rate_probe(video: Mapping[str, object]) -> bool:
    """Remote edit lists can move an average across its encoded cadence bucket."""
    average = probe_frame_rate(video)
    nominal = _positive_fraction(video.get("r_frame_rate"))
    return (
        average is not None
        and nominal is not None
        and average > float(nominal)
        and FpsBucket.from_fps(average) is not FpsBucket.from_fps(float(nominal))
    )
