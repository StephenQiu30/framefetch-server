"""Private extension installation, upgrade and ordinary LaunchAgent lifecycle."""

import json
import os
import plistlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.core.config import CookieSourceSettings
from app.workers.identity import cli, extension
from app.workers.runner.settings import RunnerSettings
from pydantic import SecretStr, ValidationError

TOKEN = "synthetic-test-only-runner-token-32-bytes"


@pytest.fixture
def installation(tmp_path, monkeypatch):
    environment, target, home = (
        tmp_path / "identity.env",
        tmp_path / "agent.plist",
        tmp_path / "FrameFetch/extension",
    )
    monkeypatch.setattr(cli, "agent_path", lambda: target)
    monkeypatch.setattr(extension, "extension_home", lambda: home)
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(cli.subprocess, "run", run)
    return environment, target, home, run


def test_install_private_config_separate_keys_and_no_secrets_in_plist(installation):
    environment, target, home, run = installation
    assert cli.install(environment) == home
    settings = cli.configured(environment)
    assert settings.cookie_source_token != settings.cookie_source_pairing_key
    spec = plistlib.loads(target.read_bytes())
    assert "LimitLoadToSessionType" not in spec and "SessionCreate" not in spec
    assert settings.cookie_source_token.get_secret_value() not in target.read_text()
    assert (
        settings.cookie_source_pairing_key.get_secret_value() not in target.read_text()
    )
    assert spec["ProgramArguments"][-1] == str(environment)
    assert spec["StandardErrorPath"] == "/dev/null"
    assert home.stat().st_mode & 0o777 == 0o700
    for path in (*home.iterdir(), environment, target):
        assert path.stat().st_mode & 0o777 == 0o600
    assert (
        settings.cookie_source_pairing_key.get_secret_value()
        in (home / "config.js").read_text()
    )
    assert run.call_args_list[0].args[0][2] == f"gui/{os.getuid()}"
    cli.uninstall()
    assert not target.exists()


def test_upgrade_preserves_keys_and_reloads_only_own_agent(installation):
    environment, _, home, run = installation
    cli.install(environment)
    before = environment.read_bytes()
    (home / "background.js").write_text("old")
    cli.install(environment)
    assert environment.read_bytes() == before
    assert (home / "background.js").read_text() == (
        extension.EXTENSION_SOURCE / "background.js"
    ).read_text()
    assert any(call.args[0][1] == "bootout" for call in run.call_args_list)


def test_supplied_runner_token_preserved(installation):
    environment, _, _, _ = installation
    environment.write_text(f"COOKIE_SOURCE_TOKEN={TOKEN}\n")
    environment.chmod(0o600)
    cli.install(environment)
    settings = cli.configured(environment)
    assert settings.cookie_source_token.get_secret_value() == TOKEN
    assert settings.cookie_source_pairing_key.get_secret_value() != TOKEN


def test_failed_bootstrap_cleans_plist(installation):
    environment, target, _, run = installation
    run.side_effect = RuntimeError("launch failed")
    with pytest.raises(RuntimeError):
        cli.install(environment)
    assert not target.exists()
    assert run.call_args_list[0].args[0][2].startswith("gui/")


def test_unrelated_agent_and_symlink_config_preserved(installation, tmp_path):
    environment, target, _, _ = installation
    target.write_bytes(plistlib.dumps({"Label": "unrelated"}))
    before = target.read_bytes()
    with pytest.raises(ValueError, match="agent_invalid"):
        cli.install(environment)
    assert target.read_bytes() == before
    environment.unlink()
    protected = tmp_path / "keep"
    protected.write_text("keep")
    environment.symlink_to(protected)
    with pytest.raises(ValueError, match="owner_only"):
        cli.install(environment)
    assert protected.read_text() == "keep"


def test_env_permissions_and_repr_hide_secrets(installation):
    environment, _, _, _ = installation
    cli.install(environment)
    settings = cli.configured(environment)
    assert settings.cookie_source_token.get_secret_value() not in repr(settings)
    assert settings.cookie_source_pairing_key.get_secret_value() not in repr(settings)
    environment.chmod(0o644)
    with pytest.raises(ValueError, match="owner_only"):
        cli.configured(environment)


def test_install_never_edits_project_env(tmp_path):
    environment = tmp_path / ".env"
    environment.write_text("preserved")
    with pytest.raises(ValueError, match="separate_env_file"):
        cli.prepare_config(environment)
    assert environment.read_text() == "preserved"


def test_manifest_registry_permissions_and_stable_id():
    manifest = json.loads((extension.EXTENSION_SOURCE / "manifest.json").read_text())
    assert manifest == extension.manifest(19101)
    assert manifest["permissions"] == ["cookies", "alarms"]
    assert manifest["minimum_chrome_version"] == "120"
    assert set(manifest["host_permissions"]) == {
        *(f"*://*.{domain}/*" for domain in extension.cookie_domains()),
        "ws://127.0.0.1:19101/",
    }
    assert "web_accessible_resources" not in manifest
    assert len(extension.extension_origin().removeprefix("chrome-extension://")) == 32
    assert extension.manifest(19102)["key"] == manifest["key"]


@pytest.mark.parametrize("token", ["short", "x" * 32 + "\n", "x" * 32 + " ", "界" * 32])
def test_unsafe_tokens_rejected(token):
    with pytest.raises(ValidationError):
        CookieSourceSettings(
            cookie_source_token=SecretStr(token),
            cookie_source_pairing_key=SecretStr("p" * 32),
        )
    with pytest.raises(ValidationError):
        CookieSourceSettings(
            cookie_source_token=SecretStr(TOKEN),
            cookie_source_pairing_key=SecretStr(token),
        )
    with pytest.raises(ValidationError):
        RunnerSettings(
            runner_hmac_secret=SecretStr("h" * 32),
            runner_egress_proxy="http://proxy:3128",
            cookie_source_token=SecretStr(token),
        )


@pytest.mark.parametrize("token", [None, ""])
def test_anonymous_runner_disabled(token):
    assert (
        RunnerSettings(
            runner_hmac_secret=SecretStr("h" * 32),
            runner_egress_proxy="http://proxy:3128",
            cookie_source_token=token,
        ).cookie_source_token
        is None
    )
