from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.workers.session.browser_source import BrowserSource, SourceUnavailable
from app.workers.session.source_cli import SourceConfig, agent_spec


def cookie(name="SID", value="synthetic", domain=".youtube.com"):
    return dict(
        name=name,
        value=value,
        domain=domain,
        path="/",
        expires=4102444800,
        secure=True,
        httpOnly=True,
        sameSite="Lax",
    )


class Context:
    def __init__(self, values):
        self.values = values
        self.closed = 0
        self.pages = [SimpleNamespace(bring_to_front=AsyncMock())]

    async def cookies(self):
        return self.values

    async def close(self):
        self.closed += 1


async def test_scoped_material_generation_and_restart_invalidation(
    tmp_path, monkeypatch
):
    source = BrowserSource(tmp_path, proxy="http://127.0.0.1:13128", secret=b"s" * 32)
    context = Context([cookie(), cookie("foreign", "never-export", ".google.com")])
    launch = AsyncMock(return_value=context)
    monkeypatch.setattr(source, "_launch", launch)
    first = await source.read("youtube.com")
    assert b"never-export" not in first.cookies
    assert b"SID" in first.cookies
    assert "synthetic" not in repr(first)
    context.values.append(cookie("analytics", "changed"))
    assert (await source.read("youtube.com")).generation == first.generation
    context.values[0] = cookie(value="another-account-or-rotated-auth")
    assert (await source.read("youtube.com")).generation != first.generation
    context.values[0] = cookie()
    restarted = BrowserSource(tmp_path, proxy=source.proxy, secret=b"s" * 32)
    monkeypatch.setattr(restarted, "_launch", launch)
    assert (await restarted.read("youtube.com")).generation != first.generation
    assert context.closed == 4


async def test_logged_out_unknown_site_and_private_fields_are_not_exported(
    tmp_path, monkeypatch
):
    source = BrowserSource(tmp_path, proxy="http://127.0.0.1:13128", secret=b"s" * 32)
    context = Context([cookie(domain=".evil-youtube.com"), cookie(value="bad\nvalue")])
    launch = AsyncMock(return_value=context)
    monkeypatch.setattr(source, "_launch", launch)
    with pytest.raises(SourceUnavailable, match="credential_required"):
        await source.read("youtube.com")
    with pytest.raises(SourceUnavailable, match="provider_session_not_allowed"):
        await source.read("arbitrary.example")
    with pytest.raises(SourceUnavailable, match="provider_session_not_allowed"):
        await source.open_login("../youtube.com")
    assert launch.await_count == 1 and context.closed == 1


async def test_active_login_reuses_browser_and_never_starts_parallel_profile(
    tmp_path, monkeypatch
):
    source = BrowserSource(tmp_path, proxy="http://127.0.0.1:13128", secret=b"s" * 32)
    context = Context([cookie()])
    source._logins["youtube.com"] = context
    launch = AsyncMock()
    monkeypatch.setattr(source, "_launch", launch)
    await source.open_login("youtube.com")
    await source.read("youtube.com")
    assert not context.closed
    launch.assert_not_awaited()
    await source.finish_login("youtube.com")
    assert context.closed == 1


async def test_launch_preserves_chromium_sandbox_proxy_and_excludes_secrets(
    tmp_path, monkeypatch
):
    source = BrowserSource(tmp_path, proxy="http://127.0.0.1:13128", secret=b"s" * 32)
    launch = AsyncMock(return_value=Context([]))
    source._playwright = SimpleNamespace(
        chromium=SimpleNamespace(launch_persistent_context=launch)
    )
    monkeypatch.setenv("SITE_SESSION_AGENT_SECRET", "must-not-reach-browser")
    monkeypatch.setenv("DATABASE_URL", "must-not-reach-browser")
    await source._launch("youtube.com", visible=False)
    args, kwargs = launch.call_args
    assert args[0] == str(tmp_path / "youtube.com")
    assert kwargs["chromium_sandbox"] is True
    assert kwargs["proxy"] == {"server": source.proxy}
    assert "--proxy-bypass-list=<-loopback>" in kwargs["args"]
    assert (
        "SITE_SESSION_AGENT_SECRET" not in kwargs["env"]
        and "DATABASE_URL" not in kwargs["env"]
    )
    assert (tmp_path / "youtube.com").stat().st_mode & 0o777 == 0o700


def test_launch_agent_receives_only_source_configuration(tmp_path):
    spec = agent_spec(SourceConfig(b"s" * 32, tmp_path, "http://127.0.0.1:13128"))
    assert "--env-file" not in spec["ProgramArguments"]
    assert set(spec["EnvironmentVariables"]) == {
        "PATH",
        "SITE_SESSION_AGENT_SECRET",
        "SITE_SESSION_PROFILE_ROOT",
        "SITE_SESSION_BROWSER_PROXY",
    }


async def test_cancelled_login_closes_browser_and_releases_capacity(
    tmp_path, monkeypatch
):
    import asyncio

    source = BrowserSource(tmp_path, proxy="http://127.0.0.1:13128", secret=b"s" * 32)
    context = Context([])
    entered = asyncio.Event()

    async def goto(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    context.pages[0].goto = goto
    monkeypatch.setattr(source, "_launch", AsyncMock(return_value=context))
    login = asyncio.create_task(source.open_login("youtube.com"))
    await entered.wait()
    login.cancel()
    with pytest.raises(asyncio.CancelledError):
        await login
    assert context.closed == 1
    assert not source._logins and not source._login_timers


def test_reinstall_retries_launchd_teardown_without_changing_material(
    tmp_path, monkeypatch
):
    import subprocess

    from app.workers.session import source_cli

    monkeypatch.setattr(source_cli.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(source_cli.time, "sleep", lambda _: None)
    bootstraps = []

    def launchctl(*args, **kwargs):
        if args[0] == "bootstrap":
            bootstraps.append(args)
            if len(bootstraps) == 1:
                raise subprocess.CalledProcessError(5, args)

    monkeypatch.setattr(source_cli, "launchctl", launchctl)
    config = SourceConfig(b"s" * 32, tmp_path / "profiles", "http://127.0.0.1:13128")
    source_cli.install(config)
    assert len(bootstraps) == 2
    assert not config.root.exists()
    plist = tmp_path / "Library/LaunchAgents/com.framefetch.browser-source.plist"
    assert plist.stat().st_mode & 0o777 == 0o600
