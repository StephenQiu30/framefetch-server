import json
import sys

import pytest
from app.core.config import Settings
from app.core.security.site_session_cipher import SiteSessionCipher
from app.services.site_sessions import known_session_sites
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
        assert 0 < timeout <= 60
        return 0, "ready"

    monkeypatch.setattr(source, "run_bounded", run)
    results = source.reconcile(tmp_path / ".env")
    assert results == dict.fromkeys(known_session_sites(), "ready")
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
    assert source.reconcile(env, background=True) == dict.fromkeys(
        known_session_sites(), "ready"
    )
    assert not startup.wait_access_check(env, request_id, timeout=1)
    assert calls.count("site") == calls.count("access") == len(known_session_sites())
    calls.clear()
    source.reconcile(env)
    assert calls == ["site"] * len(known_session_sites())
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


def test_foreground_acquisition_cannot_certify_background_permissions(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(source, "source_directory", lambda _: tmp_path)
    monkeypatch.setattr(source, "load_settings", lambda _: Settings(_env_file=None))
    calls = []
    monkeypatch.setattr(
        source,
        "run_bounded",
        lambda command, **kw: (calls.append(command[3]) or 0, "ready"),
    )
    request = tmp_path / "access-request"
    request.write_text("background-only")
    source.reconcile(tmp_path / ".env")
    assert set(calls) == {"site"}
    assert request.read_text() == "background-only"
    assert not (tmp_path / "access-status.json").exists()


def test_source_round_deadline_bounds_queued_children(tmp_path, monkeypatch):
    monkeypatch.setattr(source, "source_directory", lambda _: tmp_path)
    monkeypatch.setattr(source, "load_settings", lambda _: Settings(_env_file=None))
    ticks = iter([0] + [91] * 100)
    monkeypatch.setattr(source.time, "monotonic", lambda: next(ticks))

    def unexpected(*args, **kwargs):
        raise AssertionError("expired work must not start a child")

    monkeypatch.setattr(source, "run_bounded", unexpected)
    assert source.reconcile(tmp_path / ".env") == dict.fromkeys(
        known_session_sites(), "source_timeout"
    )


def test_source_children_are_concurrent_but_bounded(tmp_path, monkeypatch):
    from threading import Barrier, Lock

    monkeypatch.setattr(source, "source_directory", lambda _: tmp_path)
    monkeypatch.setattr(
        source,
        "load_settings",
        lambda _: Settings(
            _env_file=None, site_session_source_sites=known_session_sites()[:3]
        ),
    )
    barrier, lock = Barrier(3), Lock()
    active = peak = 0

    def run(command, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        barrier.wait(timeout=2)
        with lock:
            active -= 1
        return 0, "ready"

    monkeypatch.setattr(source, "run_bounded", run)
    assert len(source.reconcile(tmp_path / ".env")) == 3
    assert peak == 3


def test_startup_launches_business_before_host_acquisition(tmp_path, monkeypatch):
    from types import SimpleNamespace

    env = tmp_path / ".env"
    env.touch()
    monkeypatch.setattr(
        sys, "argv", ["startup", "up", "--no-build", "--env-file", str(env)]
    )
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(startup.shutil, "which", lambda _: "/usr/local/bin/docker")
    monkeypatch.setattr(
        startup,
        "load_settings",
        lambda _: Settings(
            _env_file=None, site_session_encryption_key=Fernet.generate_key().decode()
        ),
    )
    calls = []

    async def schema(_):
        pass

    monkeypatch.setattr(startup, "apply_schema", schema)
    monkeypatch.setattr(
        startup.subprocess,
        "run",
        lambda command, **kw: calls.append(command) or SimpleNamespace(returncode=0),
    )

    def acquire(_):
        assert any("up" in command for command in calls)
        raise RuntimeError("host access unavailable")

    monkeypatch.setattr(startup, "reconcile", acquire)
    assert startup.main() == 4
    assert len(calls) == 1


@pytest.mark.parametrize(
    "session_code,public_code,access_ready", [(2, 0, True), (0, 1, True), (0, 0, False)]
)
def test_startup_reports_every_readiness_failure_without_stopping_business(
    tmp_path, monkeypatch, session_code, public_code, access_ready
):
    from types import SimpleNamespace

    env = tmp_path / ".env"
    env.touch()
    monkeypatch.setattr(
        sys, "argv", ["startup", "up", "--no-build", "--env-file", str(env)]
    )
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(startup.shutil, "which", lambda _: "/usr/local/bin/docker")
    monkeypatch.setattr(
        startup,
        "load_settings",
        lambda _: Settings(
            _env_file=None, site_session_encryption_key=Fernet.generate_key().decode()
        ),
    )

    async def schema(_):
        pass

    monkeypatch.setattr(startup, "apply_schema", schema)
    monkeypatch.setattr(startup, "reconcile", lambda _: {})
    monkeypatch.setattr(startup, "install_agent", lambda *a: None)
    monkeypatch.setattr(startup, "request_access_check", lambda _: "this-start")
    monkeypatch.setattr(startup, "wait_access_check", lambda *a: access_ready)
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(
            returncode=session_code
            if "verify" in command
            else public_code
            if "--native-public" in command
            else 0
        )

    monkeypatch.setattr(startup.subprocess, "run", run)
    assert startup.main() != 0
    assert len(commands) == 3
    assert "up" in commands[0]
    assert not any("stop" in c or "down" in c for c in commands)
    verify = next(c for c in commands if "verify" in c)
    assert verify[verify.index("--sites") + 1 :] == list(known_session_sites())
