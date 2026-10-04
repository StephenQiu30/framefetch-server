from __future__ import annotations

import asyncio
import json
import os
import signal
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Protocol

from app.integrations.ai_cli.errors import AnalysisCliError


class CodexAppServerInvoker(Protocol):
    async def invoke(
        self,
        *,
        root: Path,
        prompt: str,
        schema: object,
        duration_ms: int | None,
        image_paths: tuple[Path, ...] = (),
    ) -> object: ...


class AppServerProtocolFailure(RuntimeError):
    def __init__(self, detail: bytes, *, unavailable: bool = False) -> None:
        self.detail = detail
        self.unavailable = unavailable


async def completed_result(
    process: asyncio.subprocess.Process,
    thread_id: str,
    turn_id: str,
    result_maximum: int,
    protocol_maximum: int,
) -> object:
    final_text: str | None = None
    while True:
        message = await read_message(process, protocol_maximum)
        method = message.get("method")
        params = message.get("params")
        if not isinstance(params, Mapping):
            continue
        if method == "item/completed":
            item = params.get("item")
            candidate = agent_text(item)
            if candidate is not None:
                final_text = candidate
            continue
        if method != "turn/completed" or params.get("threadId") != thread_id:
            continue
        turn = params.get("turn")
        if not isinstance(turn, Mapping) or turn.get("id") != turn_id:
            continue
        if turn.get("status") != "completed":
            error = turn.get("error")
            raise AppServerProtocolFailure(json.dumps(error).encode())
        for item in turn.get("items", []):
            candidate = agent_text(item)
            if candidate is not None:
                final_text = candidate
        return parse_result(final_text, result_maximum)


async def response(
    process: asyncio.subprocess.Process, request_id: int, maximum: int
) -> Mapping[str, object]:
    while True:
        message = await read_message(process, maximum)
        if message.get("id") != request_id:
            continue
        error = message.get("error")
        if error is not None:
            raise AppServerProtocolFailure(json.dumps(error).encode())
        result = message.get("result")
        if not isinstance(result, Mapping):
            raise AppServerProtocolFailure(
                b"invalid app server response", unavailable=True
            )
        return result


async def read_message(
    process: asyncio.subprocess.Process, maximum: int
) -> Mapping[str, object]:
    if process.stdout is None:
        raise AppServerProtocolFailure(
            b"app server stdout unavailable", unavailable=True
        )
    try:
        line = await process.stdout.readline()
    except (ValueError, asyncio.LimitOverrunError) as exc:
        raise AnalysisCliError("analysis_resource_limit") from exc
    if not line:
        raise AppServerProtocolFailure(b"app server exited", unavailable=True)
    if len(line) > maximum:
        raise AnalysisCliError("analysis_resource_limit")
    try:
        value = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppServerProtocolFailure(
            b"invalid app server message", unavailable=True
        ) from exc
    if not isinstance(value, Mapping):
        raise AppServerProtocolFailure(b"invalid app server message", unavailable=True)
    return value


def nested_string(value: Mapping[str, object], *path: str) -> str | None:
    current: object = value
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current if isinstance(current, str) and current else None


def agent_text(value: object) -> str | None:
    if not isinstance(value, Mapping) or value.get("type") != "agentMessage":
        return None
    text = value.get("text")
    return text if isinstance(text, str) and text else None


def parse_result(text: str | None, maximum: int) -> object:
    if text is None or len(text.encode()) > maximum:
        raise AnalysisCliError("invalid_model_output", outcome_known=True)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AnalysisCliError("invalid_model_output", outcome_known=True) from exc


async def drain(stream: asyncio.StreamReader, maximum: int) -> bytes:
    data = bytearray()
    while chunk := await stream.read(64 * 1024):
        remaining = maximum - len(data)
        if remaining > 0:
            data.extend(chunk[:remaining])
    return bytes(data)


async def terminate(process: asyncio.subprocess.Process, grace: float) -> None:
    if process.stdin is not None:
        process.stdin.close()
        with suppress(BrokenPipeError, ConnectionResetError):
            await process.stdin.wait_closed()
    if process.returncode is not None:
        return
    if os.name == "nt":
        process.terminate()
    else:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), grace)
    except TimeoutError:
        if os.name == "nt":
            process.kill()
        else:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
