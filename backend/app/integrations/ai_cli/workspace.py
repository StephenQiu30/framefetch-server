from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
from collections.abc import Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.integrations.ai_cli.errors import AnalysisCliError
from app.services.analysis_execution.models import VideoAnalysisRequest

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


class WorkspacePolicyConfig(Protocol):
    @property
    def max_workspace_bytes(self) -> int: ...

    @property
    def max_workspace_files(self) -> int: ...

    @property
    def max_frames(self) -> int: ...

    @property
    def max_image_bytes(self) -> int: ...

    @property
    def workspace_poll_seconds(self) -> float: ...


@dataclass(frozen=True, slots=True)
class JobFiles:
    root: Path
    schema: Path
    result: Path
    claude_settings: Path


def prepare_job_files(
    request: VideoAnalysisRequest,
    schema: dict[str, Any],
    prompt: str,
) -> JobFiles:
    try:
        root = request.workspace.resolve(strict=True)
        artifact = request.artifact.resolve(strict=True)
        expected_artifact = root / "input" / "video.bin"
        if not artifact.is_relative_to(root) or artifact != expected_artifact:
            raise OSError
        if request.image_paths:
            if (
                len(request.image_paths) != len(request.image_digests)
                or len(request.image_paths) > 12
            ):
                raise OSError
            for image, digest in zip(
                request.image_paths, request.image_digests, strict=True
            ):
                if image.is_symlink() or not image.resolve(strict=True).is_relative_to(
                    root / "work"
                ):
                    raise OSError
                if (
                    image.stat().st_size > 20 * 1024**2
                    or hashlib.sha256(image.read_bytes()).hexdigest() != digest
                ):
                    raise OSError
        for relative in (
            "policy",
            "work/frames",
            "work/contact-sheets",
            "output",
            "tmp",
        ):
            directory = root / relative
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory.chmod(0o700)
        manifest = {
            "stage": request.stage,
            "duration_ms": request.duration_ms,
            "size_bytes": request.size_bytes,
            "container": request.container,
            "input": "input/video.bin",
        }
        _write_json(root / "input" / "manifest.json", manifest)
        schema_path = root / "policy" / "output-schema.json"
        _write_json(schema_path, schema)
        _write_text(root / "policy" / "prompt.txt", prompt)
        settings = root / "policy" / "claude-settings.json"
        _write_json(settings, _claude_policy(root))
        from app.services.analysis.skills.upstream_catalog import (
            prepare_resource_policy,
        )

        prepare_resource_policy(root, request.skill_instructions)
        return JobFiles(root, schema_path, root / "output" / "result.json", settings)
    except OSError as exc:
        raise AnalysisCliError("analysis_media_invalid") from exc


async def run_with_workspace_policy[ResultT](
    operation: Coroutine[Any, Any, ResultT],
    *,
    root: Path,
    config: WorkspacePolicyConfig,
) -> ResultT:
    process_task = asyncio.create_task(operation)
    monitor_task = asyncio.create_task(_monitor(root, config))
    try:
        done, _ = await asyncio.wait(
            {process_task, monitor_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if monitor_task in done:
            failure = monitor_task.exception()
            if failure is not None:
                raise failure
        result = await process_task
        await asyncio.to_thread(_validate_workspace, root, config)
        return result
    except BaseException:
        if not process_task.done():
            process_task.cancel()
        await asyncio.gather(process_task, return_exceptions=True)
        raise
    finally:
        if not monitor_task.done():
            monitor_task.cancel()
        await asyncio.gather(monitor_task, return_exceptions=True)


async def _monitor(root: Path, config: WorkspacePolicyConfig) -> None:
    while True:
        await asyncio.to_thread(_validate_workspace, root, config)
        await asyncio.sleep(config.workspace_poll_seconds)


def _validate_workspace(root: Path, config: WorkspacePolicyConfig) -> None:
    files = 0
    frames = 0
    total = 0
    try:
        for directory, names, filenames in os.walk(root, followlinks=False):
            base = Path(directory)
            for name in names:
                if (base / name).is_symlink():
                    raise OSError
            for name in filenames:
                path = base / name
                info = path.lstat()
                runtime_special = path.is_relative_to(root / "tmp") and (
                    stat.S_ISSOCK(info.st_mode) or stat.S_ISFIFO(info.st_mode)
                )
                if runtime_special:
                    continue
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                    raise OSError
                files += 1
                total += info.st_size
                if path.suffix.lower() in _IMAGE_SUFFIXES:
                    frames += 1
                    if info.st_size > config.max_image_bytes:
                        raise OSError
                if info.st_nlink != 1:
                    raise OSError
                if (
                    files > config.max_workspace_files
                    or frames > config.max_frames
                    or total > config.max_workspace_bytes
                ):
                    raise OSError
    except OSError as exc:
        raise AnalysisCliError("analysis_resource_limit") from exc


def _write_json(path: Path, value: object) -> None:
    _write_text(path, json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)


def _claude_policy(root: Path) -> dict[str, Any]:
    return {
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "autoAllowBashIfSandboxed": False,
            "allowUnsandboxedCommands": False,
            "filesystem": {
                "denyRead": ["~/"],
                "allowRead": [str(root)],
            },
            "network": {"strictAllowlist": True, "allowedDomains": []},
        }
    }
