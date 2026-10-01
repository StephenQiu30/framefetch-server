"""Native ABI, Aqua guard, complete ACL parsing and bounded subprocess tests."""

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


@pytest.mark.parametrize("attrs,status", [(0, 0), (0, -60500)])
def test_non_aqua_or_unknown_session_never_starts_security(monkeypatch, attrs, status):
    fake_library(monkeypatch, attrs=attrs, session_status=status)
    unexpected = Mock(side_effect=AssertionError("security must not run"))
    monkeypatch.setattr(keychain.subprocess, "Popen", unexpected)
    with pytest.raises(keychain.KeychainUnavailable, match="aqua_session_required"):
        keychain.storage_password()
    unexpected.assert_not_called()


def test_aqua_reads_fixed_keychain_without_launchctl(monkeypatch):
    fake_library(monkeypatch, attrs=16)
    process = Mock(returncode=0, pid=123)
    process.communicate.return_value = (b"synthetic-key\n", None)
    spawn = Mock(return_value=process)
    monkeypatch.setattr(keychain.subprocess, "Popen", spawn)
    password, evidence = keychain.storage_password()
    assert password == b"synthetic-key" and evidence["graphic_access"]
    assert spawn.call_args.args[0] == [
        "/usr/bin/security",
        "find-generic-password",
        "-w",
        "-s",
        "Chrome Safe Storage",
        "-a",
        "Chrome",
        str(keychain.login_keychain()),
    ]
    assert spawn.call_args.kwargs["start_new_session"]
    assert spawn.call_args.kwargs["stderr"] == subprocess.DEVNULL
    process.communicate.assert_called_once_with(timeout=5)


@pytest.mark.parametrize(
    "failure", [subprocess.TimeoutExpired("security", 5), SystemExit(143)]
)
def test_timeout_or_termination_kills_entire_group(monkeypatch, failure):
    fake_library(monkeypatch, attrs=16)
    process = Mock(pid=123)
    process.communicate.side_effect = [failure, (b"", None)]
    monkeypatch.setattr(keychain.subprocess, "Popen", Mock(return_value=process))
    kill = Mock()
    monkeypatch.setattr(keychain.os, "killpg", kill)
    with pytest.raises(
        keychain.KeychainUnavailable
        if isinstance(failure, subprocess.TimeoutExpired)
        else SystemExit
    ):
        keychain.storage_password()
    kill.assert_called_once_with(123, keychain.signal.SIGKILL)
    assert process.communicate.call_count == 2


@pytest.mark.parametrize("returncode", [36, 44, 45])
def test_read_denial_does_not_retry_or_expose_material(monkeypatch, returncode):
    fake_library(monkeypatch, attrs=16)
    process = Mock(returncode=returncode)
    process.communicate.return_value = (b"private-value", None)
    spawn = Mock(return_value=process)
    monkeypatch.setattr(keychain.subprocess, "Popen", spawn)
    with pytest.raises(
        keychain.KeychainUnavailable, match="keychain_read_denied"
    ) as caught:
        keychain.storage_password()
    assert "private-value" not in str(caught.value) and spawn.call_count == 1


# Synthetic metadata only; reflects the complete security dump grammar.
ACL = b"""keychain: "/synthetic/login.keychain-db"
class: "genp"
attributes:
    "acct"<blob>="Chrome"
    "svce"<blob>="Chrome Safe Storage"
access: 3 entries
    entry 0:
        authorizations (1): encrypt
        don't-require-password
        description: synthetic
        applications: <null>
    entry 1:
        authorizations (2): decrypt derive
        don't-require-password
        description: synthetic
        applications (1):
            0: /usr/bin/security (OK)
                requirement: identifier "com.apple.security" and anchor apple
    entry 2:
        authorizations (1): partition_id
        don't-require-password
        description: teamid:SYNTHETIC, apple-tool:, apple:
        applications: <null>
"""


def test_complete_acl_and_fixed_dump_command(monkeypatch):
    fake_library(monkeypatch, attrs=16)
    process = Mock(returncode=0)
    process.communicate.return_value = (ACL, None)
    spawn = Mock(return_value=process)
    monkeypatch.setattr(keychain.subprocess, "Popen", spawn)
    evidence = keychain.validate_storage_acl()
    assert evidence["acl_valid"] and evidence["acl_entries"] == 3
    assert "synthetic" not in str(evidence)
    assert spawn.call_args.args[0] == [
        "/usr/bin/security",
        "dump-keychain",
        "-a",
        str(keychain.login_keychain()),
    ]


@pytest.mark.parametrize(
    "before,after",
    [
        (b'"Chrome"', b'"Other"'),
        (b'"Chrome Safe Storage"', b'"Other"'),
        (b'"genp"', b'"inet"'),
        (b"decrypt derive", b"encrypt derive"),
        (b"/usr/bin/security", b"/tmp/security"),
        (b"(OK)", b"(FAIL)"),
        (
            b'identifier "com.apple.security" and anchor apple',
            b'identifier "com.apple.security"',
        ),
        (b'identifier "com.apple.security"', b'identifier "evil.security"'),
        (b"apple-tool:", b"evil-tool:"),
        (b"don't-require-password", b"require-password"),
        (b"applications (1)", b"applications (2)"),
        (b"authorizations (2)", b"authorizations (3)"),
        (b"access: 3 entries", b"access: 2 entries"),
        (b"entry 2:", b"entry 3:"),
        (b"0: /usr/bin/security", b"1: /usr/bin/security"),
        (b"application", b"unknown"),
    ],
)
def test_acl_any_missing_condition_or_incomplete_structure_fails_closed(before, after):
    with pytest.raises(keychain.KeychainUnavailable, match="keychain_acl_invalid"):
        keychain.parse_storage_acl(ACL.replace(before, after))


@pytest.mark.parametrize(
    "payload",
    [
        b"invalid",
        ACL + ACL,
        ACL[:-35],
        ACL + b"unknown\n",
        ACL.replace(b"decrypt derive", b"decrypt decrypt"),
    ],
)
def test_acl_rejects_parse_failure_duplicate_item_and_truncation(payload):
    with pytest.raises(keychain.KeychainUnavailable, match="keychain_acl_invalid"):
        keychain.parse_storage_acl(payload)


def test_decrypt_requirements_cannot_be_borrowed_from_other_entry():
    payload = ACL.replace(b"decrypt derive", b"encrypt derive").replace(
        b"authorizations (1): encrypt", b"authorizations (1): decrypt"
    )
    with pytest.raises(keychain.KeychainUnavailable):
        keychain.parse_storage_acl(payload)
