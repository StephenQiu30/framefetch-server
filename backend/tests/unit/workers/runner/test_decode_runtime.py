"""Exercise delivery validation with real codecs rather than command mocks."""

import hashlib
import json
import shutil
import subprocess

import pytest
from app.services.provider_failures import FailureEvidenceKind, FailurePhase
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.process import ProcessSupervisor
from helpers import bound_commands, settings


def make_media(tmp_path, *, vfr=True, extension="mp4"):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    assert ffmpeg and ffprobe, "delivery tests require the CI FFmpeg dependencies"
    artifact = tmp_path / f"media.{extension}"
    argv = [
        ffmpeg,
        "-nostdin",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=64x64:rate=240:duration=3",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=3",
    ]
    if vfr:
        argv += [
            "-filter:v",
            "select='not(mod(n,8))+not(mod(n,9))'",
            "-fps_mode",
            "vfr",
            "-enc_time_base:v",
            "1/240",
        ]
    else:
        argv += ["-r", "30"]
    if extension == "mp4":
        argv += [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
        ]
    else:
        argv += [
            "-c:v",
            "libvpx-vp9",
            "-deadline",
            "realtime",
            "-cpu-used",
            "8",
            "-c:a",
            "libopus",
        ]
    subprocess.run([*argv, str(artifact)], check=True, capture_output=True, timeout=30)
    return artifact, ffprobe


@pytest.mark.parametrize(
    "vfr,extension", [(True, "mp4"), (False, "mp4"), (False, "webm")]
)
async def test_complete_video_and_audio_decode_without_changing_file(
    tmp_path, vfr, extension
):
    artifact, _ = make_media(tmp_path, vfr=vfr, extension=extension)
    before = hashlib.sha256(artifact.read_bytes()).hexdigest()
    await bound_commands(settings(tmp_path), ProcessSupervisor()).verify_full_decode(
        artifact, tmp_path
    )
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == before


async def test_metadata_readable_truncated_payload_cannot_be_delivered(tmp_path):
    artifact, ffprobe = make_media(tmp_path)
    content = artifact.read_bytes()
    artifact.write_bytes(content[: len(content) // 2])
    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(artifact),
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )
    metadata = json.loads(probe.stdout)
    assert float(metadata["format"]["duration"]) >= 3
    assert {stream["codec_type"] for stream in metadata["streams"]} == {
        "video",
        "audio",
    }
    with pytest.raises(RunnerFailure) as caught:
        await bound_commands(
            settings(tmp_path), ProcessSupervisor()
        ).verify_full_decode(artifact, tmp_path)
    assert caught.value.code == "invalid_artifact"
    assert caught.value.failure.phase is FailurePhase.VALIDATE
    assert caught.value.failure.evidence_kind is FailureEvidenceKind.LOCAL_VALIDATION
