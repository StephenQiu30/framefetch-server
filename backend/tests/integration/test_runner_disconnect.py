import asyncio
import json
import os
import socket
import sys
from contextlib import suppress

import httpx
import pytest
import uvicorn
from app.workers.runner.main import create_app
from app.workers.runner.process import ProcessSupervisor
from tests.unit.workers.runner.api_helpers import FakeService, settings, signed_headers


async def test_http_disconnect_terminates_real_inspection_process(tmp_path):
    cleaned = asyncio.Event()
    pid_file = tmp_path / "pid"

    class ProcessService(FakeService):
        async def inspect(self, url, **kwargs):
            try:
                await ProcessSupervisor().run(
                    [
                        sys.executable,
                        "-c",
                        "import os,time,pathlib; "
                        "pathlib.Path('pid').write_text(str(os.getpid())); "
                        "time.sleep(60)",
                    ],
                    cwd=tmp_path,
                    timeout_seconds=60,
                )
            finally:
                cleaned.set()
            return await super().inspect(url, **kwargs)

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings(tmp_path), service=ProcessService()),
            log_level="error",
            access_log=False,
        )
    )
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    request = None
    try:
        async with asyncio.timeout(10):
            while not server.started:
                await asyncio.sleep(0.01)
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{listener.getsockname()[1]}",
                trust_env=False,
                timeout=60,
            ) as client:
                path = "/internal/inspect"
                body = json.dumps({"url": "https://example.com/video"}).encode()
                request = asyncio.create_task(
                    client.post(
                        path,
                        content=body,
                        headers=signed_headers(path, body, "disconnect-test-nonce"),
                    )
                )
                while not pid_file.exists():
                    if request.done():
                        pytest.fail(
                            "inspection ended before process start: "
                            f"{request.result().status_code}"
                        )
                    await asyncio.sleep(0.01)
                pid = int(pid_file.read_text())
                os.kill(pid, 0)
                request.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await request
                await cleaned.wait()
                with pytest.raises(ProcessLookupError):
                    os.kill(pid, 0)
    finally:
        if request is not None:
            request.cancel()
            with suppress(asyncio.CancelledError):
                await request
        server.should_exit = True
        await asyncio.wait_for(serving, 10)
        listener.close()
