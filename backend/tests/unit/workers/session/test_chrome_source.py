import asyncio
import os
import sys
from pathlib import Path

import pytest
from app.workers.runner.process import ProcessResult, ProcessSupervisor
from app.workers.session.chrome_source import ChromeSource, SourceUnavailable


def jar(value="synthetic", *, analytics="one", domain=".youtube.com", name="SID"):
    return (
        "# Netscape HTTP Cookie File\n"
        f"{domain}\tTRUE\t/\tTRUE\t4102444800\t{name}\t{value}\n"
        f"{domain}\tTRUE\t/\tTRUE\t4102444800\tanalytics\t{analytics}\n"
    ).encode()


@pytest.fixture
def profile(tmp_path):
    path = tmp_path / "Default"
    path.mkdir()
    (path / "Cookies").touch()
    return path


async def source_with_payload(profile, monkeypatch, payload):
    source = ChromeSource(secret=b"s" * 32, profile=profile)

    async def read(_site):
        return payload

    monkeypatch.setattr(source, "_read", read)
    await source.start()
    return source


async def test_material_version_survives_source_restart_and_ignores_analytics(
    profile, monkeypatch
):
    first = await source_with_payload(profile, monkeypatch, jar())
    snapshot = await first.read("youtube.com")
    assert "synthetic" not in repr(snapshot)
    await first.close()
    restarted = await source_with_payload(profile, monkeypatch, jar(analytics="two"))
    assert (await restarted.read("youtube.com")).generation == snapshot.generation
    rotated = await source_with_payload(profile, monkeypatch, jar("rotated"))
    assert (await rotated.read("youtube.com")).generation != snapshot.generation
    await restarted.close()
    await rotated.close()


async def test_profile_and_secret_are_part_of_material_identity(profile, monkeypatch):
    first = await source_with_payload(profile, monkeypatch, jar())
    generation = (await first.read("youtube.com")).generation
    other = await source_with_payload(profile.parent / "Other", monkeypatch, jar())
    assert (await other.read("youtube.com")).generation != generation
    first._secret = b"r" * 32
    assert (await first.read("youtube.com")).generation != generation
    await first.close()
    await other.close()


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (jar(domain=".evil-youtube.com"), "source_read_failed"),
        (b"invalid\nsecret", "source_read_failed"),
        (jar(name="analytics-only"), "credential_required"),
    ],
)
async def test_child_material_is_validated_again_at_parent_boundary(
    profile, monkeypatch, payload, code
):
    source = await source_with_payload(profile, monkeypatch, payload)
    with pytest.raises(SourceUnavailable, match=code):
        await source.read("youtube.com")
    await source.close()


async def test_unapproved_site_and_page_header_requirement_do_not_read_chrome(
    profile, monkeypatch
):
    source = ChromeSource(secret=b"s" * 32, profile=profile)

    async def forbidden(_site):
        pytest.fail("Chrome must not be read")

    monkeypatch.setattr(source, "_read", forbidden)
    with pytest.raises(SourceUnavailable, match="provider_session_not_ready"):
        await source.read("youtube.com")
    await source.start()
    with pytest.raises(SourceUnavailable, match="provider_session_not_allowed"):
        await source.read("../youtube.com")
    with pytest.raises(SourceUnavailable, match="provider_session_not_ready"):
        await source.read("weixin.qq.com", include_headers=True)
    await source.close()


async def test_missing_profile_is_distinct_from_missing_account(tmp_path):
    source = ChromeSource(secret=b"s" * 32, profile=tmp_path / "missing")
    await source.start()
    with pytest.raises(SourceUnavailable, match="chrome_profile_unavailable"):
        await source.read("youtube.com")
    await source.close()


@pytest.mark.parametrize(
    ("returncode", "truncated", "code"),
    [
        (77, False, "credential_access_denied"),
        (66, False, "chrome_profile_unavailable"),
        (67, False, "credential_required"),
        (65, False, "source_read_failed"),
        (0, True, "source_read_failed"),
    ],
)
async def test_child_failure_is_preserved_and_temp_snapshot_is_removed(
    profile, monkeypatch, returncode, truncated, code
):
    source = ChromeSource(secret=b"s" * 32, profile=profile)
    temporary = []

    async def run(argv, *, cwd, timeout_seconds, env):
        assert argv[-1] == "youtube.com"
        assert set(env) == {"PATH", "TMPDIR"}
        assert cwd.name == "backend"
        temporary.append(Path(env["TMPDIR"]))
        assert temporary[-1].is_dir()
        (temporary[-1] / "snapshot").write_bytes(b"synthetic")
        return ProcessResult(returncode, jar(), b"never exposed", truncated, False)

    monkeypatch.setattr(source._process, "run", run)
    await source.start()
    with pytest.raises(SourceUnavailable, match=code):
        await source.read("youtube.com")
    assert temporary and not temporary[0].exists()
    await source.close()


@pytest.mark.parametrize("action", ["timeout", "cancel", "close"])
async def test_real_child_is_terminated_and_temp_directory_removed(
    profile, monkeypatch, action
):
    source = ChromeSource(secret=b"s" * 32, profile=profile, read_timeout_seconds=1)
    supervisor = ProcessSupervisor(terminate_grace_seconds=0.1)
    entered = asyncio.Event()
    child_paths = []

    async def run(argv, *, cwd, timeout_seconds, env):
        temporary = Path(env["TMPDIR"])
        child_paths.append(temporary)
        script = (
            "import os,time; from pathlib import Path; "
            "Path(os.environ['TMPDIR'], 'pid').write_text(str(os.getpid())); "
            "time.sleep(60)"
        )
        task = asyncio.create_task(
            supervisor.run(
                [sys.executable, "-c", script],
                cwd=cwd,
                timeout_seconds=timeout_seconds,
                env=env,
            )
        )
        try:
            async with asyncio.timeout(2):
                while not (temporary / "pid").exists():
                    await asyncio.sleep(0.01)
            entered.set()
            return await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    monkeypatch.setattr(source._process, "run", run)
    await source.start()
    read = asyncio.create_task(source.read("youtube.com"))
    await entered.wait()
    pid = int((child_paths[0] / "pid").read_text())
    if action == "close":
        await source.close()
    elif action == "cancel":
        read.cancel()
    expected = SourceUnavailable if action == "timeout" else asyncio.CancelledError
    with pytest.raises(expected):
        await read
    assert not child_paths[0].exists()
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert not source._reads
    await source.close()


async def test_close_cancels_active_read_and_rejects_queued_read(profile, monkeypatch):
    source = ChromeSource(secret=b"s" * 32, profile=profile)
    entered = asyncio.Event()
    calls = []

    async def read(site):
        calls.append(site)
        entered.set()
        await asyncio.Event().wait()
        return jar()

    monkeypatch.setattr(source, "_read", read)
    await source.start()
    active = asyncio.create_task(source.read("youtube.com"))
    await entered.wait()
    queued = asyncio.create_task(source.read("douyin.com"))
    await asyncio.sleep(0)
    await source.close()
    with pytest.raises(asyncio.CancelledError):
        await active
    with pytest.raises(SourceUnavailable, match="provider_session_not_ready"):
        await queued
    assert calls == ["youtube.com"]


@pytest.mark.parametrize("timeout", [0, 61])
def test_invalid_bounds_rejected(profile, timeout):
    with pytest.raises(ValueError):
        ChromeSource(secret=b"s" * 32, profile=profile, read_timeout_seconds=timeout)
