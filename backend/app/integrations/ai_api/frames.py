from __future__ import annotations

import asyncio
import base64
import math
from dataclasses import dataclass, field
from pathlib import Path

from app.integrations.ai_api.config import ApiAdapterConfig
from app.integrations.ai_cli.errors import AnalysisCliError
from app.workers.runner.process import ProcessSupervisor, ProcessTimeoutError

_FRAME_LIMIT = 64
_TOTAL_EVIDENCE_LIMIT = 24 * 1024**2


@dataclass(frozen=True, slots=True)
class FrameEvidence:
    timestamp_ms: int
    jpeg: bytes = field(repr=False)

    @property
    def data_url(self) -> str:
        encoded = base64.b64encode(self.jpeg).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"


class ApiFrameExtractor:
    def __init__(
        self,
        config: ApiAdapterConfig,
        *,
        supervisor: ProcessSupervisor | None = None,
    ) -> None:
        self._config = config
        self._supervisor = supervisor or ProcessSupervisor(
            stdout_limit_bytes=config.max_stdout_bytes,
            stderr_limit_bytes=config.max_stderr_bytes,
            terminate_grace_seconds=config.terminate_grace_seconds,
        )

    async def extract(
        self,
        video: Path,
        *,
        workspace: Path,
        duration_ms: int,
        observation_ms: tuple[int, ...] = (),
    ) -> tuple[FrameEvidence, ...]:
        limit = min(_FRAME_LIMIT, self._config.max_frames)
        if any(
            type(value) is not int or not 0 <= value < duration_ms
            for value in observation_ms
        ):
            raise AnalysisCliError("analysis_media_invalid")
        targets = tuple(dict.fromkeys(observation_ms))[: limit // 2]
        count = min(
            limit - len(targets),
            max(4, math.ceil(duration_ms / 1_000)),
        )
        output = workspace / "work" / "api-frames"
        output.mkdir(parents=True, exist_ok=True, mode=0o700)
        for stale in output.glob("frame-*.jpg"):
            stale.unlink()
        fps = count * 1_000 / duration_ms
        argv = (
            str(self._config.ffmpeg),
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-an",
            "-sn",
            "-vf",
            f"fps={fps:.8f}:start_time=0,"
            "scale=960:-2:force_original_aspect_ratio=decrease",
            "-frames:v",
            str(count),
            "-q:v",
            "4",
            "-y",
            str(output / "frame-%04d.jpg"),
        )
        try:
            result = await self._supervisor.run(
                argv,
                cwd=workspace,
                timeout_seconds=self._config.timeout_seconds,
            )
        except ProcessTimeoutError as exc:
            raise AnalysisCliError("analysis_cli_timeout") from exc
        except OSError as exc:
            raise AnalysisCliError("analysis_cli_unavailable") from exc
        if result.returncode != 0:
            raise AnalysisCliError("analysis_media_invalid")
        evidence = list(
            await asyncio.to_thread(self._read_frames, output, count, duration_ms)
        )
        for index, timestamp in enumerate(targets):
            target = output / f"revisit-{index:03d}.jpg"
            try:
                result = await self._supervisor.run(
                    (
                        str(self._config.ffmpeg),
                        "-hide_banner",
                        "-nostdin",
                        "-loglevel",
                        "error",
                        "-ss",
                        f"{timestamp / 1000:.3f}",
                        "-i",
                        str(video),
                        "-an",
                        "-sn",
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=960:-2:force_original_aspect_ratio=decrease",
                        "-q:v",
                        "4",
                        "-y",
                        str(target),
                    ),
                    cwd=workspace,
                    timeout_seconds=self._config.timeout_seconds,
                )
                if result.returncode != 0:
                    raise AnalysisCliError("analysis_media_invalid")
                raw = await asyncio.to_thread(target.read_bytes)
            except ProcessTimeoutError as exc:
                raise AnalysisCliError("analysis_cli_timeout") from exc
            except OSError as exc:
                raise AnalysisCliError("analysis_media_invalid") from exc
            if (
                not raw
                or len(raw) > min(self._config.max_image_bytes, 4 * 1024**2)
                or sum(len(item.jpeg) for item in evidence) + len(raw)
                > _TOTAL_EVIDENCE_LIMIT
            ):
                raise AnalysisCliError("analysis_resource_limit")
            evidence.append(FrameEvidence(timestamp, raw))
        return tuple(sorted(evidence, key=lambda item: item.timestamp_ms))

    def _read_frames(
        self, output: Path, requested: int, duration_ms: int
    ) -> tuple[FrameEvidence, ...]:
        try:
            paths = tuple(sorted(output.glob("frame-*.jpg")))
            if not paths or len(paths) > requested:
                raise AnalysisCliError("analysis_media_invalid")
            total = 0
            evidence: list[FrameEvidence] = []
            per_image_limit = min(self._config.max_image_bytes, 4 * 1024**2)
            for index, path in enumerate(paths):
                raw = path.read_bytes()
                total += len(raw)
                if (
                    not raw
                    or len(raw) > per_image_limit
                    or total > _TOTAL_EVIDENCE_LIMIT
                ):
                    raise AnalysisCliError("analysis_resource_limit")
                timestamp = min(duration_ms - 1, round(index * duration_ms / requested))
                evidence.append(FrameEvidence(timestamp, raw))
            return tuple(evidence)
        except OSError as exc:
            raise AnalysisCliError("analysis_media_invalid") from exc
