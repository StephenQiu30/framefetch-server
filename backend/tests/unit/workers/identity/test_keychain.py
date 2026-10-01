"""Native ABI, no-UI guard, race refusal and bounded subprocess regression tests."""

import ctypes
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.workers.identity import keychain


class Native:
    def __init__(self, function):
        self.function = function
        self.argtypes = self.restype = None

    def __call__(self, *args):
        return self.function(*args)


def fake_library(monkeypatch, *, status=0, bits=7, session_status=0, attrs=0):
    calls = []

    def opened(path, pointer):
        calls.append("open")
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_void_p))[0] = 123
        return 0

    def queried(reference, pointer):
        calls.append("status")
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32))[0] = bits
        return status

    def session(caller, session_id, attributes):
        calls.append("session")
        assert caller == 0xFFFFFFFF
        ctypes.cast(session_id, ctypes.POINTER(ctypes.c_uint32))[0] = 42
        ctypes.cast(attributes, ctypes.POINTER(ctypes.c_uint32))[0] = attrs
        return session_status

    library = SimpleNamespace(
        SecKeychainOpen=Native(opened),
        SecKeychainGetStatus=Native(queried),
        CFRelease=Native(lambda _: calls.append("release")),
        SessionGetInfo=Native(session),
    )
    monkeypatch.setattr(keychain.ctypes, "CDLL", lambda *_: library)
    monkeypatch.setattr(keychain.sys, "platform", "darwin")
    return calls, library


def test_lock_precheck_only_queries_status_and_releases_reference(monkeypatch):
    calls, lib = fake_library(monkeypatch)
    keychain.require_unlocked()
    assert calls == ["open", "status", "release"]
    assert lib.SecKeychainGetStatus.restype == ctypes.c_int32
    assert lib.SecKeychainGetStatus.argtypes == [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]


@pytest.mark.parametrize("bits", [0, 2, 6])
def test_locked_keychain_never_looks_up_item_or_unlocks(monkeypatch, bits):
    calls, _ = fake_library(monkeypatch, bits=bits)
    with pytest.raises(keychain.KeychainUnavailable, match="keychain_locked"):
        keychain.require_unlocked()
    assert calls == ["open", "status", "release"]


def test_status_failure_is_released_and_fails_closed(monkeypatch):
    calls, _ = fake_library(monkeypatch, status=-1)
    with pytest.raises(keychain.KeychainUnavailable, match="keychain_status_failed"):
        keychain.require_unlocked()
    assert calls[-1] == "release"


@pytest.mark.parametrize("attrs,status", [(16, 0), (48, 0), (0, -60500)])
def test_graphical_or_unknown_session_never_starts_security(monkeypatch, attrs, status):
    calls, _ = fake_library(monkeypatch, attrs=attrs, session_status=status)
    unexpected = Mock(side_effect=AssertionError("security must not run"))
    monkeypatch.setattr(keychain.subprocess, "Popen", unexpected)
    with pytest.raises(keychain.KeychainUnavailable, match="graphic_session_refused"):
        keychain.read_in_child()
    unexpected.assert_not_called()
    assert calls == ["session"]


def test_actual_child_checks_session_before_fixed_security_command(monkeypatch):
    calls, _ = fake_library(monkeypatch)
    process = Mock(returncode=0, pid=123)
    process.communicate.return_value = (b"synthetic-key\n", None)

    def spawn(command, **kwargs):
        assert calls == ["session"]
        assert command == [
            "/usr/bin/security",
            "find-generic-password",
            "-w",
            "-s",
            "Chrome Safe Storage",
            "-a",
            "Chrome",
        ]
        assert kwargs["start_new_session"] and kwargs["stderr"] == subprocess.DEVNULL
        return process

    monkeypatch.setattr(keychain.subprocess, "Popen", spawn)
    password, evidence = keychain.read_in_child()
    assert password == b"synthetic-key"
    assert evidence == {
        "status": 0,
        "session_id": 42,
        "attributes": 0,
        "graphic_access": False,
    }
    process.communicate.assert_called_once_with(timeout=5)


@pytest.mark.parametrize("returncode", [36, 44, 45])
def test_lock_race_or_acl_denial_never_falls_back_or_exposes_material(
    monkeypatch, returncode
):
    fake_library(monkeypatch)
    process = Mock(returncode=returncode)
    process.communicate.return_value = (b"private-value", None)
    spawn = Mock(return_value=process)
    monkeypatch.setattr(keychain.subprocess, "Popen", spawn)
    with pytest.raises(
        keychain.KeychainUnavailable, match="keychain_read_denied"
    ) as caught:
        keychain.read_in_child()
    assert "private-value" not in str(caught.value)
    assert spawn.call_count == 1


def test_security_timeout_kills_entire_group(monkeypatch):
    fake_library(monkeypatch)
    process = Mock(pid=123)
    process.communicate.side_effect = [
        subprocess.TimeoutExpired("security", 5),
        (b"", None),
    ]
    monkeypatch.setattr(keychain.subprocess, "Popen", Mock(return_value=process))
    kill = Mock()
    monkeypatch.setattr(keychain.os, "killpg", kill)
    with pytest.raises(keychain.KeychainUnavailable, match="keychain_read_timeout"):
        keychain.read_in_child()
    kill.assert_called_once_with(123, keychain.signal.SIGKILL)
    assert process.communicate.call_count == 2


def test_launchctl_failure_still_boots_out_transient_job_and_removes_files(monkeypatch):
    monkeypatch.setattr(keychain.sys, "platform", "darwin")
    calls = []
    paths = []

    def run(command, **kwargs):
        import plistlib
        from pathlib import Path

        calls.append(command)
        if command[1] == "bootstrap":
            path = Path(command[-1])
            paths.append(path)
            spec = plistlib.loads(path.read_bytes())
            assert command[2].startswith("user/")
            assert spec["SessionCreate"] is True
            assert spec["LimitLoadToSessionType"] == "Background"
            assert "security" not in spec["ProgramArguments"]
            assert path.stat().st_mode & 0o777 == 0o600
        return SimpleNamespace(returncode=5)

    monkeypatch.setattr(keychain.subprocess, "run", run)
    with pytest.raises(
        keychain.KeychainUnavailable, match="launchd_user_domain_unavailable"
    ):
        keychain.launchd_storage_password(5)
    assert [item[1] for item in calls] == ["bootstrap", "bootout"]
    assert all(not path.parent.exists() for path in paths)


def test_read_child_termination_cleans_security_process_group(monkeypatch):
    fake_library(monkeypatch)
    process = Mock(pid=123)
    process.communicate.side_effect = [SystemExit(143), (b"", None)]
    monkeypatch.setattr(keychain.subprocess, "Popen", Mock(return_value=process))
    kill = Mock()
    monkeypatch.setattr(keychain.os, "killpg", kill)
    with pytest.raises(SystemExit):
        keychain.read_in_child()
    kill.assert_called_once_with(123, keychain.signal.SIGKILL)
