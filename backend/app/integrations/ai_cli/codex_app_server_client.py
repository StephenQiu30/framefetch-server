from __future__ import annotations

import asyncio
import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

from app.integrations.ai_cli.codex_app_server_protocol import (
    AppServerProtocolFailure,
    completed_result,
    drain,
    nested_string,
    response,
    terminate,
)
from app.integrations.ai_cli.codex_mcp import video_observer_arguments
from app.integrations.ai_cli.codex_policy import codex_permission_arguments
from app.integrations.ai_cli.config import CliAdapterConfig
from app.integrations.ai_cli.environment import child_environment
from app.integrations.ai_cli.errors import AnalysisCliError, classify_cli_failure


class CodexAppServerClient:
    """Run one bounded, ephemeral Codex App Server conversation over stdio."""

    def __init__(self, config: CliAdapterConfig) -> None:
        self._config = config

    async def invoke(
        self,
        *,
        root: Path,
        prompt: str,
        schema: object,
        duration_ms: int | None,
        image_paths: tuple[Path, ...] = (),
    ) -> object:
        process: asyncio.subprocess.Process | None = None
        stderr_task: asyncio.Task[bytes] | None = None
        failure: AppServerProtocolFailure | None = None
        try:
            process = await self._spawn(root, duration_ms)
            assert process.stderr is not None
            stderr_task = asyncio.create_task(
                drain(process.stderr, self._config.max_stderr_bytes)
            )
            try:
                result = await asyncio.wait_for(
                    self._exchange(process, root, prompt, schema, image_paths),
                    timeout=self._config.timeout_seconds,
                )
            except TimeoutError:
                raise AnalysisCliError("analysis_cli_timeout") from None
            except AppServerProtocolFailure as exc:
                failure = exc
                result = None
        except OSError as exc:
            raise AnalysisCliError("analysis_cli_unavailable") from exc
        finally:
            if process is not None:
                await terminate(process, self._config.terminate_grace_seconds)
        stderr = await stderr_task if stderr_task is not None else b""
        if failure is not None:
            if failure.unavailable:
                if not stderr:
                    raise AnalysisCliError("analysis_cli_unavailable")
                raise classify_cli_failure(stderr)
            detail = failure.detail or stderr
            raise classify_cli_failure(detail)
        return result

    async def _spawn(
        self, root: Path, duration_ms: int | None
    ) -> asyncio.subprocess.Process:
        argv = self.command(root, duration_ms)
        options: dict[str, object] = {
            "cwd": root,
            "env": child_environment(self._config, root),
            "stdin": asyncio.subprocess.PIPE,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "limit": self._config.max_protocol_message_bytes,
        }
        if os.name == "nt":
            options["creationflags"] = int(
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
        else:
            options["start_new_session"] = True
        return await asyncio.create_subprocess_exec(*argv, **options)  # type: ignore[arg-type]

    def command(self, root: Path, duration_ms: int | None) -> tuple[str, ...]:
        argv = [
            str(self._config.binary),
            "--ask-for-approval",
            "never",
            "--strict-config",
            "--disable",
            "plugins",
            *self._config.provider_arguments,
            "-c",
            "mcp_servers={}",
            *codex_permission_arguments(),
            "-c",
            'web_search="disabled"',
        ]
        if duration_ms is not None:
            argv.extend(
                video_observer_arguments(
                    self._config, root=root, duration_ms=duration_ms
                )
            )
        argv.extend(("app-server", "--listen", "stdio://"))
        return tuple(argv)

    async def _exchange(
        self,
        process: asyncio.subprocess.Process,
        root: Path,
        prompt: str,
        schema: object,
        image_paths: tuple[Path, ...] = (),
    ) -> object:
        await _send(
            process,
            1,
            "initialize",
            {
                "clientInfo": {
                    "name": "video_server",
                    "title": "Video Server",
                    "version": "1",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        await response(process, 1, self._config.max_protocol_message_bytes)
        await _notify(process, "initialized", {})
        await _send(
            process,
            2,
            "thread/start",
            {
                "approvalPolicy": "never",
                "cwd": str(root),
                "ephemeral": True,
                "model": self._config.model,
                "permissions": "video_analysis",
                "runtimeWorkspaceRoots": [str(root)],
            },
        )
        started = await response(process, 2, self._config.max_protocol_message_bytes)
        thread_id = nested_string(started, "thread", "id")
        if thread_id is None:
            raise AppServerProtocolFailure(
                b"invalid thread/start response", unavailable=True
            )
        await _send(
            process,
            3,
            "turn/start",
            {
                "threadId": thread_id,
                "input": [
                    {"type": "text", "text": prompt},
                    *[
                        {"type": "localImage", "path": str(path)}
                        for path in image_paths
                    ],
                ],
                "outputSchema": schema,
            },
        )
        turn = await response(process, 3, self._config.max_protocol_message_bytes)
        turn_id = nested_string(turn, "turn", "id")
        if turn_id is None:
            raise AppServerProtocolFailure(
                b"invalid turn/start response", unavailable=True
            )
        return await completed_result(
            process,
            thread_id,
            turn_id,
            self._config.max_stdout_bytes,
            self._config.max_protocol_message_bytes,
        )


async def _send(
    process: asyncio.subprocess.Process,
    request_id: int,
    method: str,
    params: Mapping[str, object],
) -> None:
    await _write(process, {"id": request_id, "method": method, "params": params})


async def _notify(
    process: asyncio.subprocess.Process, method: str, params: Mapping[str, object]
) -> None:
    await _write(process, {"method": method, "params": params})


async def _write(process: asyncio.subprocess.Process, value: object) -> None:
    if process.stdin is None:
        raise AppServerProtocolFailure(
            b"app server stdin unavailable", unavailable=True
        )
    process.stdin.write(json.dumps(value, separators=(",", ":")).encode() + b"\n")
    try:
        await process.stdin.drain()
    except (BrokenPipeError, ConnectionResetError) as exc:
        raise AppServerProtocolFailure(b"app server exited", unavailable=True) from exc
