"""Controlled, local-only FFmpeg evidence on the original source timeline."""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import signal
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SkillOutput:
    text: str
    data: dict[str, object]
    limitations: list[str]


async def run_media_tool(
    arguments: list[str],
    *,
    timeout_seconds: float = 600,
    limit_bytes: int = 4_000_000,
    environment: dict[str, str] | None = None,
    working_directory: Path | None = None,
) -> tuple[bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *arguments,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=os.name == "posix",
        env=environment,
        cwd=working_directory,
    )

    async def collect(stream: asyncio.StreamReader | None) -> bytes:
        assert stream is not None
        result = bytearray()
        while chunk := await stream.read(65536):
            result.extend(chunk)
            if len(result) > limit_bytes:
                raise ValueError("media tool output resource limit")
        return bytes(result)

    try:
        async with asyncio.timeout(timeout_seconds):
            stdout, stderr = await asyncio.gather(
                collect(process.stdout), collect(process.stderr)
            )
            if await process.wait() != 0:
                raise ValueError("media tool failed")
            return stdout, stderr
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            await process.wait()


async def probe_video(source: Path, ffprobe: Path) -> dict[str, object]:
    if (
        source.is_symlink()
        or not source.is_file()
        or source.stat().st_size > 2 * 1024**3
    ):
        raise ValueError("invalid video or exceeds 2 GiB")
    stdout, _ = await run_media_tool(
        [
            str(ffprobe),
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(source),
        ],
        timeout_seconds=30,
        limit_bytes=100000,
    )
    payload = json.loads(stdout)
    container = payload.get("format", {})
    if "mp4" not in str(container.get("format_name", "")):
        raise ValueError("only MP4 video is supported")
    streams = payload.get("streams", [])
    video = next(
        (stream for stream in streams if stream.get("codec_type") == "video"), None
    )
    if video is None:
        raise ValueError("video stream is missing")
    duration = float(container.get("duration", "0"))
    origin = float(container.get("start_time", "0"))
    start = float(video.get("start_time", str(origin)))
    video_duration = float(video.get("duration", str(duration)))
    if (
        not math.isfinite(duration)
        or not 0 < duration <= 1800
        or not math.isfinite(start)
        or not math.isfinite(origin)
        or not math.isfinite(video_duration)
        or video_duration <= 0
    ):
        raise ValueError("invalid video duration or exceeds 30 minutes")
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    if (
        width <= 0
        or height <= 0
        or max(width, height) > 4096
        or width * height > 4096 * 2160
    ):
        raise ValueError("video decode pixel limit exceeded")
    video_start = max(0, round((start - origin) * 1000))
    video_end = min(round(duration * 1000), video_start + round(video_duration * 1000))
    if video_end <= video_start:
        raise ValueError("video time mapping is invalid")
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    audio_start: int | None = None
    audio_end: int | None = None
    if audio is not None:
        audio_origin = float(audio.get("start_time", str(origin)))
        audio_duration = float(audio.get("duration", str(duration)))
        if (
            not math.isfinite(audio_origin)
            or not math.isfinite(audio_duration)
            or audio_duration <= 0
        ):
            raise ValueError("audio time mapping is invalid")
        audio_start = max(0, round((audio_origin - origin) * 1000))
        audio_end = min(
            round(duration * 1000), audio_start + round(audio_duration * 1000)
        )
        if audio_end <= audio_start:
            raise ValueError("audio time mapping is invalid")
    return {
        "duration_ms": round(duration * 1000),
        "source_start_ms": round(start * 1000),
        "timeline_origin_ms": round(origin * 1000),
        "video_start_ms": video_start,
        "video_end_ms": video_end,
        "time_coordinate": "media_playback_relative_to_container_start",
        "time_base": str(video.get("time_base", "")),
        "average_frame_rate": str(video.get("avg_frame_rate", "")),
        "real_frame_rate": str(video.get("r_frame_rate", "")),
        "has_audio": any(stream.get("codec_type") == "audio" for stream in streams),
        "audio_start_ms": audio_start,
        "audio_end_ms": audio_end,
    }


async def study_shots(source: Path, ffmpeg: Path, ffprobe: Path) -> SkillOutput:
    metadata = await probe_video(source, ffprobe)
    _, stderr = await run_media_tool(
        [
            str(ffmpeg),
            "-hide_banner",
            "-nostdin",
            "-protocol_whitelist",
            "file,pipe",
            "-f",
            "mov",
            "-i",
            str(source),
            "-an",
            "-vf",
            "select='gt(scene,0.30)',showinfo",
            "-fps_mode",
            "vfr",
            "-f",
            "null",
            "-",
        ]
    )
    duration = int(str(metadata["duration_ms"]))
    video_start = int(str(metadata["video_start_ms"]))
    video_end = int(str(metadata["video_end_ms"]))
    cuts = sorted(
        {
            round(float(value) * 1000)
            for value in re.findall(rb"pts_time:([0-9.e+-]+)", stderr)
            if video_start < float(value) * 1000 < video_end
        }
    )
    if len(cuts) > 2000:
        raise ValueError("shot candidate limit exceeded")
    boundaries = [video_start, *cuts, video_end]
    shots: list[dict[str, object]] = [
        {
            "id": f"shot-{index + 1}",
            "start_ms": start,
            "end_ms": end,
            "observation": "",
            "sound_annotation": "",
            "confirmed": False,
            "boundary_kind": "candidate",
        }
        for index, (start, end) in enumerate(
            zip(boundaries, boundaries[1:], strict=False)
        )
    ]
    body = "# 镜头候选\n\n" + "\n".join(
        f"- {shot['id']}：{shot['start_ms']}–{shot['end_ms']} ms，待核查并填写观察。"
        for shot in shots
    )
    return SkillOutput(
        body,
        {
            "shots": shots,
            "media": metadata,
            "review_status": "needs_review",
            "unobserved_ranges": (
                [{"start_ms": 0, "end_ms": video_start}] if video_start else []
            )
            + (
                [{"start_ms": video_end, "end_ms": duration}]
                if video_end < duration
                else []
            ),
        },
        [
            "FFmpeg画面差异切点候选；叙事场景、视听观察与声音仍需人工核查。",
            "未执行非对白声音识别或自动导演意图推断。",
        ],
    )


async def extract_representative_frame(
    source: Path,
    target: Path,
    *,
    timestamp_ms: int,
    ffmpeg: Path,
    ffprobe: Path | None = None,
) -> None:
    if (
        timestamp_ms < 0
        or target.exists()
        or target.is_symlink()
        or target.suffix != ".png"
    ):
        raise ValueError("invalid frame target or timestamp")
    metadata = await probe_video(source, ffprobe or ffmpeg.with_name("ffprobe"))
    if (
        not int(str(metadata["video_start_ms"]))
        <= timestamp_ms
        < int(str(metadata["video_end_ms"]))
    ):
        raise ValueError("frame timestamp is outside the original video coverage")
    await run_media_tool(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-n",
            "-protocol_whitelist",
            "file,pipe",
            "-f",
            "mov",
            "-i",
            str(source),
            "-ss",
            f"{timestamp_ms / 1000:.3f}",
            "-frames:v",
            "1",
            "-vf",
            "scale=640:640:force_original_aspect_ratio=decrease:force_divisible_by=2",
            str(target),
        ],
        timeout_seconds=30,
        limit_bytes=100000,
    )
    if not target.is_file() or not target.stat().st_size:
        raise ValueError("frame was not produced")
