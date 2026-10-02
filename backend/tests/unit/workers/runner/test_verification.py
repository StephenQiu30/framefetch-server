from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest
from app.services.downloads.rules.enums import AudioCodecFamily, Container
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.verification import verify_probe
from helpers import download_request


def probe() -> dict[str, object]:
    return {
        "format": {"format_name": "mov,mp4,m4a", "duration": "30"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
                "color_transfer": "bt709",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    }


def verify(payload: dict[str, object], *, expected_duration: float = 30) -> None:
    verify_probe(
        payload,
        plan=download_request().plan.to_domain(),
        expected_container=Container.MP4,
        expected_duration=expected_duration,
        max_duration=7200,
        tolerance_seconds=3,
    )


@pytest.mark.parametrize(
    "case",
    ["missing_audio", "container", "duration", "dimensions", "codec"],
)
def test_rejects_artifact_that_does_not_match_plan(case: str) -> None:
    payload = deepcopy(probe())
    format_info = payload["format"]
    streams = payload["streams"]
    assert isinstance(format_info, dict)
    assert isinstance(streams, list)
    video = streams[0]
    assert isinstance(video, dict)
    if case == "missing_audio":
        payload["streams"] = streams[:1]
    elif case == "container":
        format_info["format_name"] = "matroska,webm"
    elif case == "duration":
        format_info["duration"] = "40"
    elif case == "dimensions":
        video["height"] = 720
    else:
        video["codec_name"] = "vp9"

    with pytest.raises(RunnerFailure) as caught:
        verify(payload)

    assert caught.value.code == "invalid_artifact"
    assert caught.value.status == 422


def test_accepts_a_silent_artifact_for_a_silent_plan() -> None:
    payload = probe()
    streams = payload["streams"]
    assert isinstance(streams, list)
    payload["streams"] = streams[:1]
    silent_plan = replace(
        download_request().plan.to_domain(),
        audio_codec_family=AudioCodecFamily.NONE,
        audio_language=None,
    )

    verified = verify_probe(
        payload,
        plan=silent_plan,
        expected_container=Container.MP4,
        expected_duration=30,
        max_duration=7200,
        tolerance_seconds=3,
    )

    assert verified.video_streams == 1
    assert verified.audio_streams == 0


def test_short_preview_cannot_be_published_as_a_complete_episode() -> None:
    with pytest.raises(RunnerFailure) as caught:
        verify_probe(
            probe(),
            plan=download_request().plan.to_domain(),
            expected_container=Container.MP4,
            expected_duration=1800,
            max_duration=7200,
            tolerance_seconds=3,
        )
    assert caught.value.code == "invalid_artifact"
    assert caught.value.status == 422


@pytest.mark.parametrize("rate", ["60000/1001", "0/0", "0/1", "garbage", None])
def test_frame_rate_must_match_confirmed_semantic_plan(rate):
    payload = probe()
    payload["streams"][0]["avg_frame_rate"] = rate
    with pytest.raises(RunnerFailure, match="invalid artifact"):
        verify(payload)


def test_dynamic_range_must_match_confirmed_semantic_plan():
    payload = probe()
    payload["streams"][0]["color_transfer"] = "smpte2084"
    with pytest.raises(RunnerFailure, match="invalid artifact"):
        verify(payload)


def test_exactly_one_video_stream_and_real_ntsc_rate_are_required():
    verify(probe())
    payload = probe()
    payload["streams"].append(dict(payload["streams"][0]))
    with pytest.raises(RunnerFailure, match="invalid artifact"):
        verify(payload)


@pytest.mark.parametrize("short_stream", [0, 1])
def test_long_container_cannot_hide_a_short_selected_media_stream(
    short_stream: int,
) -> None:
    payload = probe()
    payload["format"]["duration"] = "1800"
    for stream in payload["streams"]:
        stream["duration"] = "1800"
    payload["streams"][short_stream]["duration"] = "30"

    with pytest.raises(RunnerFailure, match="invalid artifact"):
        verify(payload, expected_duration=1800)


@pytest.mark.parametrize("stream_index", [0, 1])
@pytest.mark.parametrize(
    "duration",
    [
        None,
        "",
        "nan",
        "inf",
        "-inf",
        "0",
        "-1",
        "garbage",
        True,
        pytest.param(10**1000, id="overflow"),
    ],
)
def test_declared_stream_duration_must_be_finite_and_positive(
    stream_index: int, duration: object
) -> None:
    payload = probe()
    payload["streams"][stream_index]["duration"] = duration

    with pytest.raises(RunnerFailure, match="invalid artifact"):
        verify(payload)


@pytest.mark.parametrize("stream_index", [0, 1])
def test_declared_stream_duration_cannot_exceed_original_length(
    stream_index: int,
) -> None:
    payload = probe()
    payload["streams"][stream_index]["duration"] = "40"

    with pytest.raises(RunnerFailure, match="invalid artifact"):
        verify(payload)


def test_each_present_audio_stream_duration_is_checked() -> None:
    payload = probe()
    payload["streams"].append(
        {"codec_type": "audio", "codec_name": "aac", "duration": "5"}
    )

    with pytest.raises(RunnerFailure, match="invalid artifact"):
        verify(payload)


def test_declared_stream_duration_respects_maximum_within_expected_tolerance() -> None:
    payload = probe()
    payload["format"]["duration"] = "7200"
    payload["streams"][0]["duration"] = "7201"

    with pytest.raises(RunnerFailure, match="invalid artifact"):
        verify(payload, expected_duration=7200)


@pytest.mark.parametrize("video_duration,audio_duration", [("27", "33"), (None, None)])
def test_stream_durations_use_existing_tolerance_and_can_be_absent(
    video_duration: str | None, audio_duration: str | None
) -> None:
    payload = probe()
    if video_duration is not None:
        payload["streams"][0]["duration"] = video_duration
    if audio_duration is not None:
        payload["streams"][1]["duration"] = audio_duration
    verify(payload)


def test_absent_webm_stream_durations_keep_the_container_duration_check() -> None:
    payload = probe()
    payload["format"]["format_name"] = "matroska,webm"
    verified = verify_probe(
        payload,
        plan=download_request().plan.to_domain(),
        expected_container=Container.WEBM,
        expected_duration=30,
        max_duration=7200,
        tolerance_seconds=3,
    )

    assert verified.duration_seconds == 30
