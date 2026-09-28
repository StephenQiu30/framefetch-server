import json
import sys

import pytest
from app.core.config import Settings
from app.core.security.site_session_cipher import SiteSessionCipher
from app.workers.session import source, startup
from app.workers.session.seed import load_settings, source_fingerprint
from cryptography.fernet import Fernet
from pydantic import ValidationError
from tests.integration.test_site_session_seed import TARGET, choice


def test_auth_fingerprint_ignores_expiry_but_binds_site_and_value():
    cipher = SiteSessionCipher(Fernet.generate_key().decode())
    first, later = choice("one"), choice("one")
    for cookie in later.cookies:
        cookie.expires += 3600
    assert source_fingerprint(TARGET, first, cipher) == source_fingerprint(
        TARGET, later, cipher
    )
    assert source_fingerprint(TARGET, first, cipher) != source_fingerprint(
        TARGET, choice("two"), cipher
    )
    assert cipher.source_fingerprint(
        "youtube.com", b"same"
    ) != cipher.source_fingerprint("douyin.com", b"same")


def test_source_config_from_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        'SITE_SESSION_SOURCE_SITES=["douyin.com"]\n'
        'SITE_SESSION_SOURCE_PROFILES={"douyin.com":"Profile 2"}\n'
        "SITE_SESSION_SOURCE_INTERVAL_SECONDS=120\n"
    )
    settings = load_settings(env)
    assert settings.site_session_source_sites == ("douyin.com",)
    assert settings.site_session_source_profiles == {"douyin.com": "Profile 2"}
    assert settings.site_session_source_interval_seconds == 120
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None, site_session_source_profiles={"youtube.com": "../evil"}
        )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, site_session_source_sites=("unknown.com",))


def test_install_is_idempotent_and_never_embeds_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(startup.Path, "home", lambda: tmp_path)
    calls = []
    monkeypatch.setattr(
        startup, "_launchctl", lambda *args, **kwargs: calls.append(args)
    )
    env = tmp_path / "project with spaces/.env"
    spec = startup.agent_spec(env, 60)
    assert spec["ProgramArguments"][-1] == str(env)
    assert "EnvironmentVariables" not in spec
    startup.install_agent(env, 60)
    assert calls[-1][0] == "bootstrap"
    calls.clear()
    startup.install_agent(env, 60)
    assert [call[0] for call in calls] == ["print"]
    startup.uninstall_agent(env)
    assert not list((tmp_path / "Library/LaunchAgents").glob("*.plist"))


def test_reconcile_writes_only_site_results_and_uses_a_bounded_child(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(source, "source_directory", lambda _: tmp_path)
    monkeypatch.setattr(source, "load_settings", lambda _: Settings(_env_file=None))
    commands = []

    def run(command, *, timeout, cwd):
        commands.append(command)
        assert timeout == 60
        return 0, "ready"

    monkeypatch.setattr(source, "run_bounded", run)
    results = source.reconcile(tmp_path / ".env")
    assert results == {"youtube.com": "ready", "douyin.com": "ready"}
    assert all("app.workers.session.source" in command for command in commands)
    assert json.loads((tmp_path / "source-status.json").read_text())["sites"] == results
    assert (tmp_path / "source-status.json").stat().st_mode & 0o777 == 0o600


def test_child_timeout_terminates_process_group(tmp_path):
    # Exercise the real bounded execution; a stuck source must not hang launchd.
    code, result = source.run_bounded(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        timeout=1,
        cwd=tmp_path,
    )
    assert (code, result) == (4, "source_timeout")


def test_background_access_check_is_explicit_and_failed_permissions_are_not_ready(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(source, "source_directory", lambda _: tmp_path)
    monkeypatch.setattr(startup, "source_directory", lambda _: tmp_path)
    monkeypatch.setattr(startup, "_launchctl", lambda *a, **kw: None)
    monkeypatch.setattr(source, "load_settings", lambda _: Settings(_env_file=None))
    calls = []

    def run(command, **kwargs):
        calls.append(command[3])
        return (
            (3, "chrome_permission_required")
            if command[3] == "access"
            else (0, "ready")
        )

    monkeypatch.setattr(source, "run_bounded", run)
    env = tmp_path / ".env"
    request_id = startup.request_access_check(env)
    assert source.reconcile(env) == {"youtube.com": "ready", "douyin.com": "ready"}
    assert not startup.wait_access_check(env, request_id, timeout=1)
    assert calls == ["site", "access", "site", "access"]
    calls.clear()
    source.reconcile(env)
    assert calls == ["site", "site"]
    assert not (tmp_path / "access-request").exists()


def test_old_access_report_cannot_satisfy_new_startup(tmp_path, monkeypatch):
    monkeypatch.setattr(startup, "source_directory", lambda _: tmp_path)
    (tmp_path / "access-status.json").write_text(
        json.dumps(
            {
                "request_id": "old",
                "sites": {"youtube.com": "readable"},
            }
        )
    )
    assert not startup.wait_access_check(tmp_path / ".env", "new", timeout=0.01)
