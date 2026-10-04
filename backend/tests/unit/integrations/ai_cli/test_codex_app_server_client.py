# ruff: noqa: E501

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from app.integrations.ai_cli.codex_app_server_client import CodexAppServerClient
from app.integrations.ai_cli.config import CliAdapterConfig
from app.integrations.ai_cli.errors import AnalysisCliError


def config(
    binary: Path,
    *,
    max_stdout_bytes: int = 2 * 1024 * 1024,
    max_image_bytes: int = 20 * 1024**2,
) -> CliAdapterConfig:
    return CliAdapterConfig(
        binary=binary,
        model="controlled-model",
        ffmpeg=Path(sys.executable),
        ffprobe=Path(sys.executable),
        timeout_seconds=5,
        max_stdout_bytes=max_stdout_bytes,
        max_image_bytes=max_image_bytes,
    )


def fake_server(
    tmp_path: Path,
    *,
    failure: str | None = None,
    protocol_payload_bytes: int = 0,
) -> Path:
    script = tmp_path / "fake-codex"
    failure_literal = repr(failure)
    payload_bytes_literal = repr(protocol_payload_bytes)
    script.write_text(
        f"""#!{sys.executable}
import json
import sys

failure = {failure_literal}
protocol_payload_bytes = {payload_bytes_literal}
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        assert message["params"]["clientInfo"]["name"] == "video_server"
        assert message["params"]["capabilities"]["experimentalApi"] is True
        print(json.dumps({{"id": 1, "result": {{"userAgent": "fake"}}}}), flush=True)
    elif method == "initialized":
        continue
    elif method == "thread/start":
        if failure == "schema":
            print(json.dumps({{"id": 2, "error": {{"message": "invalid_json_schema"}}}}), flush=True)
            continue
        params = message["params"]
        assert params["ephemeral"] is True
        assert params["approvalPolicy"] == "never"
        assert params["permissions"] == "video_analysis"
        print(json.dumps({{"id": 2, "result": {{"thread": {{"id": "thread-1"}}}}}}), flush=True)
    elif method == "turn/start":
        params = message["params"]
        assert params["threadId"] == "thread-1"
        assert params["outputSchema"]["type"] == "object"
        print(json.dumps({{"id": 3, "result": {{"turn": {{"id": "turn-1"}}}}}}), flush=True)
        if protocol_payload_bytes:
            print(json.dumps({{"method": "item/completed", "params": {{"item": {{"type": "toolCall", "payload": "x" * protocol_payload_bytes}}}}}}), flush=True)
        if failure == "rate":
            turn = {{"id": "turn-1", "status": "failed", "items": [], "error": {{"message": "429 rate limit"}}}}
        else:
            item = {{"type": "agentMessage", "id": "item-1", "text": '{{"answer":"ok"}}'}}
            print(json.dumps({{"method": "item/completed", "params": {{"item": item}}}}), flush=True)
            turn = {{"id": "turn-1", "status": "completed", "items": [item], "error": None}}
        print(json.dumps({{"method": "turn/completed", "params": {{"threadId": "thread-1", "turn": turn}}}}), flush=True)
""",
        encoding="utf-8",
    )
    script.chmod(0o700)
    return script


@pytest.mark.asyncio
async def test_client_runs_ephemeral_structured_app_server_turn(
    tmp_path: Path,
) -> None:
    root = tmp_path / "job"
    (root / "tmp").mkdir(parents=True)
    client = CodexAppServerClient(config(fake_server(tmp_path)))

    result = await client.invoke(
        root=root,
        prompt="analyze",
        schema={"type": "object"},
        duration_ms=None,
    )

    assert result == {"answer": "ok"}
    command = client.command(root, None)
    assert "app-server" in command
    assert "stdio://" in command
    assert "exec" not in command
    assert command.count("--disable") == 1
    assert "plugins" in command
    assert "code_mode_host" not in command
    assert "mcp_servers={}" in command
    assert 'default_permissions="video_analysis"' in command
    assert not any("video_observer" in item for item in command)


@pytest.mark.asyncio
async def test_protocol_events_do_not_consume_the_final_result_budget(
    tmp_path: Path,
) -> None:
    root = tmp_path / "job"
    (root / "tmp").mkdir(parents=True)
    binary = fake_server(tmp_path, protocol_payload_bytes=4_096)
    client = CodexAppServerClient(
        config(binary, max_stdout_bytes=256, max_image_bytes=4_096)
    )

    result = await client.invoke(
        root=root,
        prompt="analyze",
        schema={"type": "object"},
        duration_ms=None,
    )

    assert result == {"answer": "ok"}


def test_protocol_limit_covers_one_base64_encoded_observation_image(
    tmp_path: Path,
) -> None:
    adapter = config(
        fake_server(tmp_path),
        max_stdout_bytes=256,
        max_image_bytes=3 * 1024 * 1024,
    )

    assert adapter.max_protocol_message_bytes >= 4 * 1024 * 1024
    assert adapter.max_protocol_message_bytes > adapter.max_stdout_bytes


def test_video_turn_enables_only_the_scoped_observer(tmp_path: Path) -> None:
    client = CodexAppServerClient(config(fake_server(tmp_path)))

    command = client.command(tmp_path, 2_000)

    assert "mcp_servers.video_observer.required=true" in command
    assert any(
        value.startswith("mcp_servers.video_observer.enabled_tools=[")
        for value in command
    )
    assert "permissions.video_analysis.network.enabled=false" in command


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "code"),
    (
        ("schema", "analysis_cli_unsupported"),
        ("rate", "analysis_provider_rate_limited"),
    ),
)
async def test_client_maps_app_server_failures(
    tmp_path: Path, failure: str, code: str
) -> None:
    root = tmp_path / "job"
    (root / "tmp").mkdir(parents=True)
    client = CodexAppServerClient(config(fake_server(tmp_path, failure=failure)))

    with pytest.raises(AnalysisCliError) as error:
        await client.invoke(
            root=root,
            prompt="analyze",
            schema={"type": "object"},
            duration_ms=None,
        )

    assert error.value.code == code
    assert error.value.no_model_execution is (failure == "schema")


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group cancellation")
async def test_cancelled_client_terminates_app_server_and_its_child_group(
    tmp_path: Path,
) -> None:
    root = tmp_path / "held-job"
    (root / "tmp").mkdir(parents=True)
    binary = fake_server(tmp_path)
    script = binary.read_text().replace(
        "        if protocol_payload_bytes:",
        """        import subprocess
        import time
        from pathlib import Path
        child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(120)"])
        Path("tmp/child.pid").write_text(str(child.pid))
        while True:
            time.sleep(1)
        if protocol_payload_bytes:""",
    )
    binary.write_text(script)

    class ObservedClient(CodexAppServerClient):
        async def _spawn(self, workspace, duration_ms):
            self.process = await super()._spawn(workspace, duration_ms)
            return self.process

    client = ObservedClient(config(binary))
    task = asyncio.create_task(
        client.invoke(
            root=root,
            prompt="controlled hold",
            schema={"type": "object"},
            duration_ms=None,
        )
    )
    try:
        async with asyncio.timeout(3):
            while not (root / "tmp/child.pid").exists():
                await asyncio.sleep(0.01)
        group = client.process.pid
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client.process.returncode is not None
        async with asyncio.timeout(3):
            while True:
                try:
                    os.killpg(group, 0)
                except ProcessLookupError:
                    break
                await asyncio.sleep(0.05)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
