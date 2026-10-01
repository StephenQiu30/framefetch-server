"""LaunchAgent lifecycle and typed identity configuration without live launchd."""

import os
import plistlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.core.config import CookieSourceSettings
from app.workers.identity import cli
from app.workers.runner.settings import RunnerSettings
from pydantic import SecretStr, ValidationError

TOKEN = "unit-test-only-identity-token-32-bytes"


def env_file(tmp_path):
    path = tmp_path / "identity.env"
    path.write_text(f"COOKIE_SOURCE_TOKEN={TOKEN}\n")
    path.chmod(0o600)
    return path


def test_launch_agent_gui_domain_aqua_session_and_no_token_in_plist(
    monkeypatch, tmp_path
):
    environment = env_file(tmp_path)
    target = tmp_path / "com.framefetch.cookie-source.plist"
    monkeypatch.setattr(cli, "agent_path", lambda: target)
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(cli.subprocess, "run", run)
    cli.install(environment)
    spec = plistlib.loads(target.read_bytes())
    assert spec["LimitLoadToSessionType"] == "Aqua" and "SessionCreate" not in spec
    assert TOKEN not in target.read_text()
    assert spec["ProgramArguments"][-1] == str(environment)
    assert target.stat().st_mode & 0o777 == 0o600
    assert run.call_args.args[0][2] == f"gui/{os.getuid()}"
    cli.uninstall()
    assert not target.exists()
    assert run.call_args.args[0][1] == "bootout"


def test_failed_bootstrap_removes_plist_and_does_not_fallback(monkeypatch, tmp_path):
    target = tmp_path / "agent.plist"
    monkeypatch.setattr(cli, "agent_path", lambda: target)
    run = Mock(side_effect=RuntimeError("launch failed"))
    monkeypatch.setattr(cli.subprocess, "run", run)
    with pytest.raises(RuntimeError):
        cli.install(env_file(tmp_path))
    assert not target.exists() and run.call_count == 1
    assert run.call_args.args[0][2].startswith("gui/")


def test_install_never_overwrites_existing_agent(monkeypatch, tmp_path):
    target = tmp_path / "agent.plist"
    target.write_text("existing-user-content")
    monkeypatch.setattr(cli, "agent_path", lambda: target)
    with pytest.raises(ValueError, match="already_installed"):
        cli.install(env_file(tmp_path))
    assert target.read_text() == "existing-user-content"


def test_env_permissions_and_repr_hide_token(tmp_path):
    environment = env_file(tmp_path)
    settings = cli.configured(environment)
    assert TOKEN not in repr(settings)
    environment.chmod(0o644)
    with pytest.raises(ValueError, match="owner_only"):
        cli.configured(environment)


@pytest.mark.parametrize("token", ["short", "x" * 32 + "\n", "x" * 32 + " ", "界" * 32])
def test_host_and_runner_refuse_unsafe_identity_tokens(token):
    with pytest.raises(ValidationError):
        CookieSourceSettings(cookie_source_token=SecretStr(token))
    with pytest.raises(ValidationError):
        RunnerSettings(
            runner_hmac_secret=SecretStr("h" * 32),
            runner_egress_proxy="http://proxy:3128",
            cookie_source_token=SecretStr(token),
        )


def test_none_is_valid_for_anonymous_runner():
    settings = RunnerSettings(
        runner_hmac_secret=SecretStr("h" * 32), runner_egress_proxy="http://proxy:3128"
    )
    assert settings.cookie_source_token is None


def test_empty_compose_token_keeps_anonymous_runner_disabled():
    settings = RunnerSettings(
        runner_hmac_secret=SecretStr("h" * 32),
        runner_egress_proxy="http://proxy:3128",
        cookie_source_token="",
    )
    assert settings.cookie_source_token is None
