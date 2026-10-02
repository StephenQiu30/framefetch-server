from __future__ import annotations

import json
import sys
from pathlib import Path

from app.integrations.ai_cli.codex_mcp import (
    observation_image_limit,
    video_observer_arguments,
)
from app.integrations.ai_cli.config import CliAdapterConfig
from app.integrations.ai_cli.media_mcp_tools import TOOLS


def _config() -> CliAdapterConfig:
    binary = Path(sys.executable)
    return CliAdapterConfig(
        binary=binary,
        model="controlled-model",
        ffmpeg=binary,
        ffprobe=binary,
    )


def test_video_observer_mcp_is_required_and_narrowly_scoped(tmp_path: Path) -> None:
    arguments = video_observer_arguments(
        _config(),
        root=tmp_path,
        duration_ms=12_345,
    )
    overrides = {
        item.split("=", 1)[0]: json.loads(item.split("=", 1)[1])
        for item in arguments
        if item != "-c"
    }

    assert overrides["mcp_servers.video_observer.required"] is True
    assert overrides["mcp_servers.video_observer.enabled_tools"] == [
        "probe_video",
        "inspect_video_overview",
        "inspect_video_frame",
    ]
    launcher = overrides["mcp_servers.video_observer.args"]
    assert launcher[:2] == ["-m", "app.integrations.ai_cli.media_mcp_server"]
    assert launcher[launcher.index("--workspace") + 1] == str(tmp_path)
    assert launcher[launcher.index("--maximum-images") + 1] == "15"
    assert "input/video.bin" not in " ".join(launcher)
    assert all(
        set(tool["inputSchema"]["properties"]).issubset(
            {"start_ms", "end_ms", "timestamp_ms"}
        )
        for tool in TOOLS
    )


def test_observation_budget_scales_with_duration_and_respects_operator_cap() -> None:
    assert observation_image_limit(duration_ms=5_000, maximum=256) == 4
    assert observation_image_limit(duration_ms=19_736, maximum=256) == 18
    assert observation_image_limit(duration_ms=600_000, maximum=256) == 256
    assert observation_image_limit(duration_ms=600_000, maximum=64) == 64
