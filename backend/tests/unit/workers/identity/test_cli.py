"""Private extension installation, upgrade and ordinary LaunchAgent lifecycle."""

import json
import os
import plistlib
import shutil
import subprocess
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
        tmp_path / "repo/browser-extension",
    )
    home.mkdir(parents=True)
    for name in (
        "background.js",
        "protocol.js",
        "yuanbao-parse.js",
        "manifest.template.json",
    ):
        shutil.copyfile(extension.EXTENSION_SOURCE / name, home / name)
    (home.parent / ".gitignore").write_text(
        "/browser-extension/config.local.json\n/browser-extension/manifest.json\n"
    )
    subprocess.run(["git", "init", "-q", str(home.parent)], check=True)
    subprocess.run(["git", "-C", str(home.parent), "add", "."], check=True)
    original_run = subprocess.run
    monkeypatch.setattr(extension, "EXTENSION_SOURCE", home)
    monkeypatch.setattr(cli, "agent_path", lambda: target)
    monkeypatch.setattr(extension, "extension_home", lambda: home)
    run = Mock(return_value=SimpleNamespace(returncode=0))

    def dispatch(argv, **kwargs):
        return original_run(argv, **kwargs) if argv[0] == "git" else run(argv, **kwargs)

    monkeypatch.setattr(cli.subprocess, "run", dispatch)
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
    for path in (
        home / "config.local.json",
        home / "manifest.json",
        environment,
        target,
    ):
        assert path.stat().st_mode & 0o777 == 0o600
    assert (
        settings.cookie_source_pairing_key.get_secret_value()
        in (home / "config.local.json").read_text()
    )
    config = json.loads((home / "config.local.json").read_text())
    assert config["yuanbaoParse"] is True
    assert "yuanbao.tencent.com" not in config["domains"]
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
    assert (home / "background.js").read_text() == "old"  # install never copies source
    extension.require_untracked_outputs(home)
    assert any(call.args[0][1] == "bootout" for call in run.call_args_list)


def test_supplied_runner_token_preserved(installation):
    environment, _, _, _ = installation
    environment.write_text(f"COOKIE_SOURCE_TOKEN={TOKEN}\n")
    environment.chmod(0o600)
    cli.install(environment)
    settings = cli.configured(environment)
    assert settings.cookie_source_token.get_secret_value() == TOKEN
    assert settings.cookie_source_pairing_key.get_secret_value() != TOKEN


def test_upgrade_waits_for_previous_launchd_registration(installation):
    environment, target, home, run = installation
    cli.install(environment)
    before = environment.read_bytes()
    registered = True

    def launchd(argv, **kwargs):
        nonlocal registered
        if argv[1] == "bootout":
            if "--wait" in argv:
                registered = False
            return SimpleNamespace(returncode=0)
        if argv[1] == "print":
            return SimpleNamespace(returncode=0 if registered else 113)
        if argv[1] == "bootstrap":
            if registered:
                raise subprocess.CalledProcessError(5, argv)
            registered = True
        return SimpleNamespace(returncode=0)

    run.side_effect = launchd
    assert cli.install(environment) == home
    assert environment.read_bytes() == before
    assert plistlib.loads(target.read_bytes())["Label"] == cli.LABEL


def test_upgrade_bootout_timeout_preserves_existing_installation(installation):
    environment, target, _, run = installation
    cli.install(environment)
    before_config, before_agent = environment.read_bytes(), target.read_bytes()

    def launchd(argv, **kwargs):
        if argv[1] == "bootout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        raise AssertionError("must not bootstrap while previous service remains")

    run.side_effect = launchd
    with pytest.raises(subprocess.TimeoutExpired):
        cli.install(environment)
    assert environment.read_bytes() == before_config
    assert target.read_bytes() == before_agent


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
    template = json.loads(
        (extension.EXTENSION_SOURCE / "manifest.template.json").read_text()
    )
    manifest = extension.manifest(19101)
    assert "host_permissions" not in template
    assert manifest["permissions"] == ["cookies", "alarms", "scripting"]
    assert manifest["minimum_chrome_version"] == "120"
    assert set(manifest["host_permissions"]) == {
        *(f"*://*.{domain}/*" for domain in extension.cookie_domains()),
        "https://yuanbao.tencent.com/*",
        "ws://127.0.0.1:19101/",
    }
    assert "web_accessible_resources" not in manifest
    assert len(extension.extension_origin().removeprefix("chrome-extension://")) == 32
    assert extension.manifest(19102)["key"] == manifest["key"]
    assert extension.page_origins() == ["https://yuanbao.tencent.com"]
    assert "channels.weixin.qq.com" not in extension.cookie_domains()
    assert "yuanbao.tencent.com" not in extension.cookie_domains()


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


@pytest.mark.parametrize("name", ["config.local.json", "manifest.json"])
def test_install_refuses_tracked_pairing_or_manifest(installation, name):
    environment, _, home, _ = installation
    generated = home / name
    generated.write_text("preserve")
    subprocess.run(["git", "-C", str(home), "add", "-f", name], check=True)
    with pytest.raises(ValueError, match="generated_file_tracked"):
        cli.install(environment)
    assert generated.read_text() == "preserve"


def test_install_refuses_worktree_generation(installation, monkeypatch, tmp_path):
    environment, _, home, _ = installation
    monkeypatch.setattr(
        extension, "EXTENSION_SOURCE", tmp_path / "worktree/browser-extension"
    )
    with pytest.raises(ValueError, match="requires_primary_workspace"):
        cli.install(environment)
    assert not (home / "config.local.json").exists()


def test_main_workspace_lookup_uses_common_git_directory(monkeypatch, tmp_path):
    common = tmp_path / "primary/.git"
    run = Mock(return_value=SimpleNamespace(stdout=str(common) + "\n"))
    monkeypatch.setattr(extension.subprocess, "run", run)
    assert extension.extension_home() == tmp_path / "primary/browser-extension"
    assert "--git-common-dir" in run.call_args.args[0]


def test_registry_permissions_cover_every_identity_platform():
    from app.services.provider_types import ProviderIdentity
    from app.workers.runner.provider_registry import current_provider_registry

    domains = set(extension.cookie_domains())
    for profile in current_provider_registry().profiles:
        if profile.identity is not ProviderIdentity.NONE:
            if profile.identity_source == "cookies":
                assert profile.cookie_domain_allowlist
                assert set(profile.cookie_domain_allowlist) <= domains
            else:
                assert profile.key == "wechat_channels"
                assert profile.identity_origin in extension.page_origins()
                assert not profile.cookie_domain_allowlist
    assert {
        "kuaishou.com",
        "weibo.com",
        "reddit.com",
    } <= domains
    assert (
        not {
            "hongguoduanju.com",
            "novelquickapp.com",
            "yuanbao.tencent.com",
            "channels.weixin.qq.com",
        }
        & domains
    )
    permissions = extension.manifest(19101)["host_permissions"]
    assert all(f"*://*.{domain}/*" in permissions for domain in domains)
    assert "*://*.tiktok.com/*" not in permissions


def test_reddit_prefer_generates_cookie_permissions_without_install():
    from app.services.provider_types import ProviderIdentity
    from app.workers.runner.provider_registry import current_provider_registry

    profile = current_provider_registry().profile_for_key("reddit")
    assert profile.identity is ProviderIdentity.PREFER
    assert profile.cookie_domain_allowlist == frozenset({"reddit.com"})
    assert "*://*.reddit.com/*" in extension.manifest(19101)["host_permissions"]


def test_host_websocket_limit_accepts_native_parse_envelope(monkeypatch, tmp_path):
    import sys

    import uvicorn
    from app.workers.identity.yuanbao_parse import YUANBAO_PARSE_MAX_MESSAGE_BYTES

    settings = CookieSourceSettings(
        cookie_source_token=SecretStr(TOKEN),
        cookie_source_pairing_key=SecretStr("synthetic-test-only-pairing-key-32-bytes"),
    )
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(
        sys,
        "argv",
        ["cookie-source", "run", "--env-file", str(tmp_path / "identity.env")],
    )
    monkeypatch.setattr(cli, "configured", lambda env_file: settings)
    run = Mock()
    monkeypatch.setattr(uvicorn, "run", run)
    assert cli.main() == 0
    assert run.call_args.kwargs["ws_max_size"] == YUANBAO_PARSE_MAX_MESSAGE_BYTES
    assert run.call_args.kwargs["host"] == "127.0.0.1"
    assert run.call_args.kwargs["access_log"] is False
