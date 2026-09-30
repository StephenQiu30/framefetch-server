"""Host startup is deterministic and never installs or starts browser integration."""

import os
import plistlib
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from app.workers.session import source_cli


@pytest.fixture(autouse=True)
def isolated_source_configuration(monkeypatch, tmp_path):
    for name in (
        "SITE_SESSION_AGENT_SECRET",
        "SITE_SESSION_CHROME_PROFILE",
        "SITE_SESSION_READ_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(source_cli.Path, "home", lambda: tmp_path)


def test_fixed_default_profile_does_not_discover_other_accounts(tmp_path):
    config = source_cli.load_config(None)
    assert config.chrome_profile == (
        tmp_path / "Library/Application Support/Google/Chrome/Default"
    )
    assert config.read_timeout_seconds == 15
    assert not config.chrome_profile.exists()


def test_environment_overrides_dotenv_without_rotating_source_secret(
    tmp_path, monkeypatch
):
    env_file = tmp_path / "source.env"
    env_file.write_text(
        f"SITE_SESSION_AGENT_SECRET={'e' * 32}\n"
        f"SITE_SESSION_CHROME_PROFILE={tmp_path / 'file-profile'}\n"
        "SITE_SESSION_READ_TIMEOUT_SECONDS=12\n"
    )
    monkeypatch.setenv("SITE_SESSION_AGENT_SECRET", "p" * 32)
    monkeypatch.setenv("SITE_SESSION_CHROME_PROFILE", "~/fixed-profile")
    config = source_cli.load_config(env_file)
    assert config.secret == b"p" * 32
    assert config.chrome_profile == Path("~/fixed-profile").expanduser()
    assert config.read_timeout_seconds == 12
    assert "p" * 32 not in repr(config)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SITE_SESSION_AGENT_SECRET", "short"),
        ("SITE_SESSION_CHROME_PROFILE", "relative-profile"),
        ("SITE_SESSION_READ_TIMEOUT_SECONDS", "NaN"),
        ("SITE_SESSION_READ_TIMEOUT_SECONDS", "inf"),
        ("SITE_SESSION_READ_TIMEOUT_SECONDS", "0"),
        ("SITE_SESSION_READ_TIMEOUT_SECONDS", "61"),
        ("SITE_SESSION_READ_TIMEOUT_SECONDS", "not-a-number"),
    ],
)
def test_invalid_source_config_has_bounded_safe_error(name, value, monkeypatch):
    monkeypatch.setenv(name, value)
    with pytest.raises(SystemExit, match=name) as error:
        source_cli.load_config(None)
    assert str(error.value).startswith(name)
    if name == "SITE_SESSION_AGENT_SECRET":
        assert value not in str(error.value)


def test_launch_agent_keeps_only_source_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "synthetic-unrelated-database-value")
    config = source_cli.SourceConfig(b"s" * 32, tmp_path / "Chrome/Default", 12)
    spec = source_cli.agent_spec(config)
    environment = spec["EnvironmentVariables"]
    assert environment == {
        "SITE_SESSION_AGENT_SECRET": "s" * 32,
        "SITE_SESSION_CHROME_PROFILE": str(config.chrome_profile),
        "SITE_SESSION_READ_TIMEOUT_SECONDS": "12",
        "PATH": os.defpath,
    }
    assert spec["RunAtLoad"] and spec["KeepAlive"]
    assert spec["StandardOutPath"] == spec["StandardErrorPath"] == "/dev/null"
    assert spec["ProgramArguments"][-1] == "serve"
    assert "--env-file" not in spec["ProgramArguments"]


def test_install_retries_only_transient_launchd_error_and_preserves_chrome(
    tmp_path, monkeypatch
):
    profile = tmp_path / "Chrome/Default"
    profile.mkdir(parents=True)
    marker = profile / "unrelated-user-data"
    marker.write_text("synthetic fixture")
    calls = []

    def launchctl(*args, **kwargs):
        calls.append(args)
        if args[0] == "bootstrap" and sum(c[0] == "bootstrap" for c in calls) == 1:
            raise subprocess.CalledProcessError(5, args)

    monkeypatch.setattr(source_cli, "launchctl", launchctl)
    monkeypatch.setattr(source_cli.time, "sleep", lambda _: None)
    source_cli.install(source_cli.SourceConfig(b"s" * 32, profile))
    destination = tmp_path / f"Library/LaunchAgents/{source_cli.SOURCE_LABEL}.plist"
    assert destination.stat().st_mode & 0o777 == 0o600
    assert (
        plistlib.loads(destination.read_bytes())["EnvironmentVariables"][
            "SITE_SESSION_AGENT_SECRET"
        ]
        == "s" * 32
    )
    assert sum(call[0] == "bootstrap" for call in calls) == 2
    assert sorted(p.name for p in profile.iterdir()) == [marker.name]
    assert sorted(p.name for p in (tmp_path / "Library").iterdir()) == ["LaunchAgents"]


def test_nontransient_install_error_does_not_retry_or_expose_configuration(
    tmp_path, monkeypatch
):
    calls = []

    def launchctl(*args, **kwargs):
        if args[0] == "bootstrap":
            calls.append(args)
            raise subprocess.CalledProcessError(37, args)

    monkeypatch.setattr(source_cli, "launchctl", launchctl)
    with pytest.raises(SystemExit, match="launchd") as error:
        source_cli.install(source_cli.SourceConfig(b"s" * 32, tmp_path / "Profile"))
    assert len(calls) == 1 and "s" * 32 not in str(error.value)


def test_uninstall_removes_only_owned_agent(tmp_path, monkeypatch):
    directory = tmp_path / "Library/LaunchAgents"
    directory.mkdir(parents=True)
    own = directory / f"{source_cli.SOURCE_LABEL}.plist"
    other = directory / "other.plist"
    own.write_text("synthetic owned job")
    other.write_text("other user's job")
    calls = []
    monkeypatch.setattr(source_cli, "launchctl", lambda *a, **k: calls.append(a))
    source_cli.uninstall()
    assert not own.exists() and other.read_text() == "other user's job"
    assert calls == [("bootout", f"gui/{os.getuid()}/{source_cli.SOURCE_LABEL}")]


@pytest.mark.parametrize("retired", ["login", "finish"])
def test_cli_rejects_retired_interactive_commands(retired, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["source_cli", retired])
    with pytest.raises(SystemExit) as error:
        source_cli.main()
    assert error.value.code == 2


def test_cli_rejects_ignored_site_configuration_for_serve(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["source_cli", "serve", "--site", "youtube.com"])
    with pytest.raises(SystemExit) as error:
        source_cli.main()
    assert error.value.code == 2


def test_serve_passes_fixed_profile_and_timeout_without_reading_accounts(
    tmp_path, monkeypatch
):
    config = source_cli.SourceConfig(b"s" * 32, tmp_path / "Profile", 12)
    captured = {}
    marker = object()
    monkeypatch.setattr(source_cli, "load_config", lambda _: config)
    monkeypatch.setattr(source_cli, "ChromeSource", lambda **k: captured.update(k))
    monkeypatch.setattr(source_cli, "create_app", lambda **_: marker)
    monkeypatch.setattr(source_cli.uvicorn, "run", lambda app, **k: captured.update(k))
    monkeypatch.setattr(sys, "argv", ["source_cli", "serve"])
    assert source_cli.main() == 0
    assert captured["secret"] == config.secret
    assert captured["profile"] == config.chrome_profile
    assert captured["read_timeout_seconds"] == 12
    assert captured["host"] == "127.0.0.1" and not captured["access_log"]


async def test_check_reports_material_readiness_without_exporting_cookie_values(
    tmp_path, monkeypatch, capsys
):
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(200, json={"site": "youtube.com", "source_generation": 7})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        source_cli.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            **kwargs, transport=httpx.MockTransport(reply)
        ),
    )
    config = source_cli.SourceConfig(b"s" * 32, Path("/synthetic/profile"))
    assert await source_cli.control(config, "youtube.com") == 0
    assert len(requests) == 1
    assert requests[0].url.path == "/internal/site-sessions/status"
    assert capsys.readouterr().out == (
        "youtube.com\tsource_ready (platform acceptance not verified)\n"
    )
