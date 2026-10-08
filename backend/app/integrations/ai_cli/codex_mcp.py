from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from app.integrations.ai_cli.config import CliAdapterConfig

_SERVER = "video_observer"
_TOOLS = ["probe_video", "inspect_video_overview", "inspect_video_frame"]


def observation_image_limit(*, duration_ms: int, maximum: int) -> int:
    if duration_ms <= 10_000:
        return min(maximum, 4)
    duration_seconds = math.ceil(duration_ms / 1_000)
    return min(maximum, 8 + math.ceil(duration_seconds / 2))


def video_observer_arguments(
    config: CliAdapterConfig,
    *,
    root: Path,
    duration_ms: int,
) -> tuple[str, ...]:
    backend = Path(__file__).resolve(strict=True).parents[3]
    arguments = [
        "-m",
        "app.integrations.ai_cli.media_mcp_server",
        "--workspace",
        str(root),
        "--ffmpeg",
        str(config.ffmpeg),
        "--ffprobe",
        str(config.ffprobe),
        "--duration-ms",
        str(duration_ms),
        "--maximum-images",
        str(
            observation_image_limit(
                duration_ms=duration_ms,
                maximum=config.max_frames,
            )
        ),
        "--maximum-image-bytes",
        str(config.max_image_bytes),
    ]
    values = {
        f"mcp_servers.{_SERVER}.command": str(Path(sys.executable).resolve()),
        f"mcp_servers.{_SERVER}.args": arguments,
        f"mcp_servers.{_SERVER}.cwd": str(backend),
        f"mcp_servers.{_SERVER}.required": True,
        f"mcp_servers.{_SERVER}.enabled_tools": _TOOLS,
        f"mcp_servers.{_SERVER}.default_tools_approval_mode": "auto",
        f"mcp_servers.{_SERVER}.startup_timeout_sec": 10,
        f"mcp_servers.{_SERVER}.tool_timeout_sec": 90,
    }
    return tuple(
        item
        for key, value in values.items()
        for item in ("-c", f"{key}={json.dumps(value)}")
    )


def skill_resource_arguments(root: Path) -> tuple[str, ...]:
    from app.services.analysis.skills.upstream_catalog import RESOURCE_POLICY

    policy = root / RESOURCE_POLICY
    if not policy.exists():
        return ()
    if policy.is_symlink() or policy.parent.is_symlink():
        raise ValueError("invalid upstream resource policy")
    values = {
        "mcp_servers.skill_resources.command": str(Path(sys.executable).resolve()),
        "mcp_servers.skill_resources.args": [
            "-m",
            "app.integrations.ai_cli.skill_resources_server",
            "--workspace",
            str(root),
        ],
        "mcp_servers.skill_resources.cwd": str(
            Path(__file__).resolve(strict=True).parents[3]
        ),
        "mcp_servers.skill_resources.required": True,
        "mcp_servers.skill_resources.enabled_tools": ["read_skill_resource"],
        "mcp_servers.skill_resources.default_tools_approval_mode": "auto",
        "mcp_servers.skill_resources.startup_timeout_sec": 10,
        "mcp_servers.skill_resources.tool_timeout_sec": 10,
    }
    return tuple(
        item
        for key, value in values.items()
        for item in ("-c", f"{key}={json.dumps(value)}")
    )
