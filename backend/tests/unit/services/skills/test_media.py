from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest
from app.services.skills.media import (
    extract_representative_frame,
    probe_video,
    run_media_tool,
    study_shots,
)
from PIL import Image


@pytest.fixture
def media_tools() -> tuple[Path, Path]:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("此用例需要真实 FFmpeg/ffprobe；未执行不等于媒体验收")
    return Path(ffmpeg), Path(ffprobe)


async def _hardcut(path: Path, ffmpeg: Path) -> None:
    await run_media_tool(
        [
            str(ffmpeg),
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
            "[0:v][1:v]concat=n=2:v=1:a=0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(path),
        ],
        timeout_seconds=15,
    )


@pytest.mark.asyncio
async def test_actual_hardcut_and_nonzero_pts_share_playback_time(
    tmp_path: Path, media_tools: tuple[Path, Path]
) -> None:
    ffmpeg, ffprobe = media_tools
    source, offset = tmp_path / "original.mp4", tmp_path / "offset.mp4"
    await _hardcut(source, ffmpeg)
    await run_media_tool(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-c",
            "copy",
            "-output_ts_offset",
            "2",
            "-y",
            str(offset),
        ]
    )
    for index, path in enumerate((source, offset)):
        metadata = await probe_video(path, ffprobe)
        assert metadata["has_audio"] is False
        assert metadata["duration_ms"] == 2000
        assert metadata["source_start_ms"] == index * 2000
        assert metadata["video_start_ms"] == 0
        result = await study_shots(path, ffmpeg, ffprobe)
        shots = result.data["shots"]
        assert [(shot["start_ms"], shot["end_ms"]) for shot in shots] == [
            (0, 1000),
            (1000, 2000),
        ]
        for timestamp, expected in ((400, 0), (1400, 253)):
            frame = tmp_path / f"frame-{index}-{timestamp}.png"
            await extract_representative_frame(
                path, frame, timestamp_ms=timestamp, ffmpeg=ffmpeg, ffprobe=ffprobe
            )
            with Image.open(frame) as image:
                image.load()
                assert abs(image.getpixel((20, 20))[0] - expected) <= 3
        with pytest.raises(ValueError, match="coverage"):
            await extract_representative_frame(
                path,
                tmp_path / f"past-{index}.png",
                timestamp_ms=2000,
                ffmpeg=ffmpeg,
                ffprobe=ffprobe,
            )


@pytest.mark.asyncio
async def test_actual_vfr_uses_pts_cut_not_average_frame_index(
    tmp_path: Path, media_tools: tuple[Path, Path]
) -> None:
    ffmpeg, ffprobe = media_tools
    source, variable = tmp_path / "original.mp4", tmp_path / "variable.mp4"
    await _hardcut(source, ffmpeg)
    await run_media_tool(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vf",
            r"select=if(lt(t\,1)\,1\,not(mod(n\,2)))",
            "-fps_mode",
            "vfr",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(variable),
        ]
    )
    result = await study_shots(variable, ffmpeg, ffprobe)
    metadata = result.data["media"]
    assert metadata["average_frame_rate"] != metadata["real_frame_rate"]
    assert result.data["shots"][0]["end_ms"] == 1040
    assert result.data["shots"][-1]["end_ms"] == metadata["video_end_ms"]
    # First white source frame is 1.040s after odd-frame filtering.
    target = tmp_path / "variable-frame.png"
    await extract_representative_frame(
        variable, target, timestamp_ms=1040, ffmpeg=ffmpeg, ffprobe=ffprobe
    )
    with Image.open(target) as image:
        image.load()
        assert image.getpixel((20, 20))[0] > 240


@pytest.mark.asyncio
async def test_actual_audio_before_video_is_not_fabricated_as_a_shot(
    tmp_path: Path, media_tools: tuple[Path, Path]
) -> None:
    ffmpeg, ffprobe = media_tools
    target = tmp_path / "staggered.mp4"
    await run_media_tool(
        [
            str(ffmpeg),
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
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono:d=3",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0,setpts=PTS+2/TB[v];[2:a]asetpts=PTS+1/TB[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-copyts",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-y",
            str(target),
        ]
    )
    result = await study_shots(target, ffmpeg, ffprobe)
    metadata = result.data["media"]
    assert metadata["has_audio"] is True
    assert metadata["timeline_origin_ms"] == 936
    assert metadata["video_start_ms"] == 1064
    assert result.data["shots"][0]["start_ms"] == 1064
    assert result.data["shots"][0]["end_ms"] == 2064
    assert result.data["unobserved_ranges"] == [{"start_ms": 0, "end_ms": 1064}]
    with pytest.raises(ValueError, match="coverage"):
        await extract_representative_frame(
            target,
            tmp_path / "no-video.png",
            timestamp_ms=100,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
        )


@pytest.mark.asyncio
async def test_bad_media_and_timeout_are_bounded(
    tmp_path: Path, media_tools: tuple[Path, Path]
) -> None:
    _, ffprobe = media_tools
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"not a movie")
    with pytest.raises(ValueError, match="failed"):
        await probe_video(fake, ffprobe)
    link = tmp_path / "link.mp4"
    link.symlink_to(fake)
    with pytest.raises(ValueError, match="invalid video"):
        await probe_video(link, ffprobe)
    with pytest.raises(TimeoutError):
        await run_media_tool(["/bin/sleep", "2"], timeout_seconds=0.01)
    await asyncio.sleep(0)
