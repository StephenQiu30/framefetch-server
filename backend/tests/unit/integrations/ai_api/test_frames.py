from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from app.integrations.ai_api.config import ApiAdapterConfig
from app.integrations.ai_api.frames import ApiFrameExtractor
from app.workers.runner.process import ProcessResult


class FakeSupervisor:
    def __init__(self) -> None:
        self.argv: tuple[str, ...] = ()
        self.calls: list[tuple[str, ...]] = []

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
        input_bytes: bytes | None = None,
    ) -> ProcessResult:
        del timeout_seconds, env, input_bytes
        self.argv = tuple(argv)
        self.calls.append(self.argv)
        if "-ss" in argv:
            Path(argv[-1]).write_bytes(b"revisit")
        else:
            output = cwd / "work" / "api-frames"
            for index in range(int(argv[argv.index("-frames:v") + 1])):
                (output / f"frame-{index + 1:04d}.jpg").write_bytes(b"frame")
        return ProcessResult(0, b"", b"", False, False)


@pytest.mark.parametrize("targets", [(), (1500, 1500, 100, 200, 300, 400, 500)])
@pytest.mark.asyncio
async def test_ffmpeg_frames_are_bounded_and_timestamped(
    tmp_path: Path, targets: tuple[int, ...]
) -> None:
    executable = Path(sys.executable)
    config = ApiAdapterConfig(
        model="deepseek-v4-flash-vision-exp",
        base_url="https://api.deepseek.com",
        ffmpeg=executable,
        ffprobe=executable,
        timeout_seconds=30,
        max_stdout_bytes=1024,
        max_stderr_bytes=1024,
        max_workspace_bytes=1024 * 1024,
        max_workspace_files=16,
        max_frames=8,
        max_image_bytes=1024,
        workspace_poll_seconds=0.1,
        terminate_grace_seconds=1,
    )
    supervisor = FakeSupervisor()
    workspace = tmp_path / "job"
    (workspace / "work").mkdir(parents=True)
    video = workspace / "video.bin"
    video.write_bytes(b"video")
    extractor = ApiFrameExtractor(
        config,
        supervisor=supervisor,  # type: ignore[arg-type]
    )

    frames = await extractor.extract(
        video, workspace=workspace, duration_ms=2_000, observation_ms=targets
    )

    expected_targets = tuple(dict.fromkeys(targets))[:4]
    assert len(frames) == 4 + len(expected_targets) <= config.max_frames
    assert [frame.timestamp_ms for frame in frames] == sorted(
        [0, 500, 1000, 1500, *expected_targets]
    )
    assert len(supervisor.calls) == 1 + len(expected_targets)
    assert all("-ss" in call for call in supervisor.calls[1:])
    assert supervisor.argv[0] == sys.executable
    assert "-an" in supervisor.argv
    assert "-sn" in supervisor.argv
    assert "-frames:v" in supervisor.argv
    assert all("http" not in value for value in supervisor.argv)
