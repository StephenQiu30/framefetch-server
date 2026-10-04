"""Successful bounded tool receipts omit model text and rejected observations."""

import hashlib
import json
import logging
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest
from app.integrations.ai_cli.media_mcp import VideoObserver
from app.integrations.ai_cli.observation_receipts import record_observation
from app.services.analysis_execution.video_observations import (
    configure_video_observation_logging,
    log_video_observations,
)
from PIL import Image
from tests.unit.workers.analysis.fakes import running_job


def test_receipts_bind_actual_returned_bytes_and_filter_private_extra_fields(
    tmp_path, caplog
):
    (tmp_path / "input").mkdir()
    (tmp_path / "work").mkdir()
    (tmp_path / "input" / "video.bin").write_bytes(b"owned source")
    (tmp_path / "input" / "manifest.json").write_text('{"stage":"review"}')
    observer = VideoObserver(
        SimpleNamespace(
            workspace=tmp_path,
            ffmpeg=sys.executable,
            ffprobe=sys.executable,
            duration_ms=2000,
            maximum_images=4,
            maximum_image_bytes=100,
        )
    )
    assert observer.call("inspect_video_frame", {"timestamp_ms": 2000})["isError"]
    assert not (tmp_path / "work" / "video-observations.jsonl").exists()
    record_observation(
        tmp_path, "inspect_video_frame", timestamps_ms=[500], image=b"image"
    )
    path = tmp_path / "work" / "video-observations.jsonl"
    receipt = json.loads(path.read_text())
    assert receipt["image_sha256"] == hashlib.sha256(b"image").hexdigest()
    receipt["private_extra"] = "credentials and model body must not leak"
    path.write_text(json.dumps(receipt) + "\n")
    job = running_job()
    with caplog.at_level(logging.INFO):
        log_video_observations(tmp_path, job)
    logged = json.loads(caplog.records[-1].message)
    assert logged["job_id"] == str(job.id) and logged["run_id"] == str(job.run_id)
    assert logged["source_sha256"] == job.input_sha256
    assert logged["timestamps_ms"] == [500] and logged["stage"] == "review"
    assert logged["image_sha256"] == receipt["image_sha256"]
    assert "private_extra" not in logged and "credentials" not in caplog.text


def test_worker_receipts_are_visible_without_enabling_unrelated_info_logs(
    tmp_path, monkeypatch, capsys
):
    logger = logging.getLogger("app.services.analysis_execution.video_observations")
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "level", logging.NOTSET)
    monkeypatch.setattr(logger, "propagate", True)
    root_level = logging.getLogger().level
    (tmp_path / "input").mkdir()
    (tmp_path / "work").mkdir()
    (tmp_path / "input" / "manifest.json").write_text('{"stage":"review"}')
    record_observation(
        tmp_path, "inspect_video_frame", timestamps_ms=[1000], image=b"image"
    )
    configure_video_observation_logging()
    configure_video_observation_logging()
    log_video_observations(tmp_path, running_job())
    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "skill_video_observation"
    assert logging.getLogger().level == root_level


def test_actual_full_local_overviews_and_single_frames_agree_at_a_hard_cut(tmp_path):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg is required for deterministic video observation proof")
    (tmp_path / "input").mkdir()
    video = tmp_path / "input" / "video.bin"
    subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x180:r=25:d=1",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=320x180:r=25:d=1",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-f",
            "mp4",
            str(video),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    (tmp_path / "input" / "manifest.json").write_text('{"stage":"review"}')
    observer = VideoObserver(
        SimpleNamespace(
            workspace=tmp_path,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            duration_ms=2000,
            maximum_images=4,
            maximum_image_bytes=4 * 1024**2,
        )
    )
    for index, (start, end) in enumerate(((0, 2000), (875, 1125)), start=1):
        result = observer.call(
            "inspect_video_overview", {"start_ms": start, "end_ms": end}
        )
        assert not result.get("isError")
        path = (
            tmp_path / "work" / "contact-sheets" / f"agent-observation-{index:03d}.jpg"
        )
        with Image.open(path) as image:
            values = [
                image.convert("RGB").getpixel(
                    (2 + (i % 4) * 322 + 160, 2 + (i // 4) * 182 + 90)
                )[0]
                for i in range(16)
            ]
        assert all(value < 16 for value in values[:8])
        assert all(value > 240 for value in values[8:])
    for index, timestamp in enumerate((960, 1000), start=3):
        result = observer.call("inspect_video_frame", {"timestamp_ms": timestamp})
        assert not result.get("isError")
        with Image.open(
            tmp_path / "work" / "frames" / f"agent-observation-{index:03d}.jpg"
        ) as image:
            value = image.convert("RGB").getpixel((160, 90))[0]
        assert value < 16 if timestamp == 960 else value > 240
    receipts = [
        json.loads(line)
        for line in (tmp_path / "work" / "video-observations.jsonl")
        .read_text()
        .splitlines()
    ]
    assert len(receipts) == 4
    assert receipts[1]["timestamps_ms"][8] == 1000
