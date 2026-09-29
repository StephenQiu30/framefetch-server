from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_credential_lease import (
    ProviderCredentialLeaseCoordinator,
    lease_key,
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def redis_url(tmp_path: Path) -> Iterator[str]:
    redis_server = shutil.which("redis-server")
    if redis_server is None:
        pytest.skip("redis-server is not installed")
    port = _free_port()
    process = subprocess.Popen(
        [
            redis_server,
            "--bind",
            "127.0.0.1",
            "--port",
            str(port),
            "--save",
            "",
            "--appendonly",
            "no",
            "--dir",
            str(tmp_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 3
        while True:
            result = subprocess.run(
                ["redis-cli", "-h", "127.0.0.1", "-p", str(port), "ping"],
                capture_output=True,
                check=False,
            )
            if result.stdout.strip() != b"PONG":
                if time.monotonic() >= deadline:
                    pytest.fail("redis-server did not become ready")
                time.sleep(0.02)
            else:
                break
        yield f"redis://127.0.0.1:{port}/0"
    finally:
        process.terminate()
        process.wait(timeout=3)


@pytest.mark.asyncio
async def test_two_replicas_cannot_hold_one_credential_at_once(
    redis_url: str,
) -> None:
    first = ProviderCredentialLeaseCoordinator(
        redis_url, ttl_seconds=3, heartbeat_seconds=1
    )
    second = ProviderCredentialLeaseCoordinator(
        redis_url, ttl_seconds=3, heartbeat_seconds=1
    )
    release = asyncio.Event()
    entered = asyncio.Event()

    async def hold_first() -> None:
        async with first.hold("youtube", "browser"):
            entered.set()
            await release.wait()

    task = asyncio.create_task(hold_first())
    await entered.wait()
    with pytest.raises(RunnerFailure, match="provider session unavailable"):
        async with second.hold("youtube", "browser"):
            raise AssertionError("the second replica acquired the lease")

    release.set()
    await task
    async with second.hold("youtube", "browser"):
        pass
    await first.close()
    await second.close()


@pytest.mark.asyncio
async def test_expired_lease_can_be_taken_over(redis_url: str) -> None:
    first = ProviderCredentialLeaseCoordinator(
        redis_url, ttl_seconds=1, heartbeat_seconds=0.2
    )
    second = ProviderCredentialLeaseCoordinator(
        redis_url, ttl_seconds=1, heartbeat_seconds=0.2
    )
    # Simulate a process crash: a token exists, but no heartbeat task can renew it.
    await first._client.set(lease_key("youtube", "browser"), "crashed", px=250)
    with pytest.raises(RunnerFailure):
        async with second.hold("youtube", "browser"):
            raise AssertionError("the expired lease was not respected")
    await asyncio.sleep(0.35)
    async with second.hold("youtube", "browser"):
        pass
    await first.close()
    await second.close()


@pytest.mark.asyncio
async def test_heartbeat_keeps_long_operation_owned(redis_url: str) -> None:
    first = ProviderCredentialLeaseCoordinator(
        redis_url, ttl_seconds=1, heartbeat_seconds=0.2
    )
    second = ProviderCredentialLeaseCoordinator(
        redis_url, ttl_seconds=1, heartbeat_seconds=0.2
    )
    async with first.hold("youtube", "browser"):
        await asyncio.sleep(1.3)
        with pytest.raises(RunnerFailure):
            async with second.hold("youtube", "browser"):
                raise AssertionError("heartbeat did not preserve the lease")
    await first.close()
    await second.close()


@pytest.mark.asyncio
async def test_waiting_holder_queues_behind_the_current_holder(
    redis_url: str,
) -> None:
    first = ProviderCredentialLeaseCoordinator(
        redis_url, ttl_seconds=3, heartbeat_seconds=1
    )
    second = ProviderCredentialLeaseCoordinator(
        redis_url, ttl_seconds=3, heartbeat_seconds=1
    )
    entered = asyncio.Event()

    async def hold_briefly() -> None:
        async with first.hold("youtube", "session"):
            entered.set()
            await asyncio.sleep(0.6)

    task = asyncio.create_task(hold_briefly())
    await entered.wait()
    started = time.monotonic()
    async with second.hold("youtube", "session", wait_seconds=5):
        assert time.monotonic() - started >= 0.4
    await task

    async with first.hold("youtube", "session"):
        started = time.monotonic()
        with pytest.raises(RunnerFailure):
            async with second.hold("youtube", "session", wait_seconds=0.5):
                raise AssertionError("the busy credential was acquired")
        assert 0.4 <= time.monotonic() - started < 2
    await first.close()
    await second.close()
