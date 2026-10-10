"""Windows generation, private ACLs and current-user service installation."""

import json
import os
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.workers.identity import cli, extension, permissions, windows_service

TOKEN = "synthetic-test-only-runner-token-32-bytes"


def test_windows_cli_install_is_supported(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.sys, "platform", "win32")
    env_file = tmp_path / "identity.env"
    monkeypatch.setattr(
        sys, "argv", ["cookie-source", "install", "--env-file", str(env_file)]
    )
    install = Mock(return_value=tmp_path / "extension")
    monkeypatch.setattr(cli, "install", install)
    assert cli.main() == 0
    install.assert_called_once_with(env_file.absolute())


def test_windows_default_config_uses_local_appdata(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert cli.default_env_file() == tmp_path / "Framefetch/identity/identity.env"


def test_task_arguments_are_data_and_failure_is_sanitized(monkeypatch, tmp_path):
    backend = tmp_path / "backend with spaces"
    python = backend / ".venv/Scripts/pythonw.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    env_file = tmp_path / "identity '界'; write-error injected.env"
    run = Mock(return_value=SimpleNamespace(returncode=2))
    monkeypatch.setattr(windows_service.subprocess, "run", run)
    with pytest.raises(ValueError, match="^cookie_source_windows_service_failed$"):
        windows_service.manage_service(backend, env_file)
    argv, kwargs = run.call_args.args[0], run.call_args.kwargs
    assert str(env_file) not in argv[-1]
    assert kwargs["env"]["FRAMEFETCH_IDENTITY_ARGUMENTS"] == subprocess.list2cmdline(
        ["-m", "app.workers.identity.cli", "run", "--env-file", str(env_file)]
    )
    assert kwargs["env"]["FRAMEFETCH_IDENTITY_PYTHON"] == str(python)
    assert kwargs["capture_output"] is True


@pytest.fixture
def windows_installation(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("requires native Windows ACLs")
    home = tmp_path / "repo/extension"
    shutil.copytree(
        extension.EXTENSION_SOURCE,
        home,
        ignore=shutil.ignore_patterns("manifest.json", "config.local.json"),
    )
    (home.parent / ".gitignore").write_text(
        "/extension/config.local.json\n/extension/manifest.json\n**/.local-runtime/\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(home.parent)], check=True)
    monkeypatch.setattr(extension, "EXTENSION_SOURCE", home)
    monkeypatch.setattr(extension, "extension_home", lambda: home)
    service = Mock()
    monkeypatch.setattr(cli, "manage_service", service)
    return tmp_path / "private/identity.env", home, service


def test_windows_install_generates_loadable_extension_and_preserves_pairing(
    windows_installation,
):
    env_file, home, service = windows_installation
    assert cli.install(env_file) == home
    settings = cli.configured(env_file)
    before = env_file.read_bytes()
    manifest = json.loads((home / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    assert manifest["name"] == "Framefetch"
    assert (home / manifest["background"]["service_worker"]).is_file()
    assert (home / manifest["action"]["default_popup"]).is_file()
    for rules in manifest["declarative_net_request"]["rule_resources"]:
        assert (home / rules["path"]).is_file()
    config = json.loads((home / "config.local.json").read_text(encoding="utf-8"))
    assert config["pairingKey"] == settings.cookie_source_pairing_key.get_secret_value()
    assert settings.cookie_source_token.get_secret_value() not in json.dumps(config)
    for path in (env_file, home / "manifest.json", home / "config.local.json"):
        permissions.require_private_file(path)
    assert cli.install(env_file) == home
    assert env_file.read_bytes() == before
    service.assert_called_with(home.parent / "backend", env_file)
    extension.require_untracked_outputs(home)


def test_windows_supplied_token_preserved(windows_installation):
    env_file, _, _ = windows_installation
    permissions.private_directory(env_file.parent)
    permissions.private_write(env_file, f"COOKIE_SOURCE_TOKEN={TOKEN}\n")
    settings = cli.prepare_config(env_file)
    assert settings.cookie_source_token.get_secret_value() == TOKEN
    assert settings.cookie_source_pairing_key.get_secret_value() != TOKEN


def test_windows_rejects_broadened_acl_before_reading_or_overwriting(
    windows_installation,
):
    env_file, _, _ = windows_installation
    cli.prepare_config(env_file)
    before = env_file.read_bytes()
    # Use a language-independent SID for the untrusted Everyone principal.
    script = """
$acl = Get-Acl -LiteralPath $env:FRAMEFETCH_TEST_PATH
$sid = [Security.Principal.SecurityIdentifier]::new('S-1-1-0')
$rule = [Security.AccessControl.FileSystemAccessRule]::new($sid, 'Read', 'Allow')
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $env:FRAMEFETCH_TEST_PATH -AclObject $acl
"""
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env={
            **{k: v for k, v in os.environ.items() if k.lower() != "psmodulepath"},
            "FRAMEFETCH_TEST_PATH": str(env_file),
        },
        check=True,
        capture_output=True,
    )
    with pytest.raises(ValueError, match="owner_only"):
        cli.configured(env_file)
    with pytest.raises(ValueError, match="owner_only"):
        cli.prepare_config(env_file)
    assert env_file.read_bytes() == before


def test_windows_rejects_junction_without_writing(tmp_path):
    if os.name != "nt":
        pytest.skip("requires native Windows junctions")
    target = tmp_path / "target"
    target.mkdir()
    junction = tmp_path / "junction"
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "New-Item -ItemType Junction -Path $env:FRAMEFETCH_TEST_LINK "
            "-Target $env:FRAMEFETCH_TEST_TARGET | Out-Null",
        ],
        env={
            **os.environ,
            "FRAMEFETCH_TEST_LINK": str(junction),
            "FRAMEFETCH_TEST_TARGET": str(target),
        },
        capture_output=True,
        check=True,
    )
    try:
        with pytest.raises(ValueError, match="symlink"):
            permissions.private_write(junction / "identity.env", TOKEN)
        assert not (target / "identity.env").exists()
    finally:
        junction.rmdir()
