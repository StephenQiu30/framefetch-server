"""Read-only Aqua-session Keychain access with complete, fail-closed ACL parsing."""

from __future__ import annotations

import ctypes
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

SECURITY_FRAMEWORK = "/System/Library/Frameworks/Security.framework/Security"
SESSION_HAS_GRAPHIC_ACCESS = 0x10


class KeychainUnavailable(Exception):
    def __init__(self, cause: str, evidence: dict[str, int | bool] | None = None):
        super().__init__(cause)
        self.cause = cause
        self.evidence = evidence or {}


def login_keychain() -> Path:
    return Path.home() / "Library/Keychains/login.keychain-db"


def keychain_status() -> int:
    """Query the login Keychain without accessing a secret item or changing state."""
    if sys.platform != "darwin":
        raise KeychainUnavailable("host_not_macos")
    security = ctypes.CDLL(SECURITY_FRAMEWORK)
    security.SecKeychainOpen.argtypes = [
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    security.SecKeychainOpen.restype = ctypes.c_int32
    security.SecKeychainGetStatus.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    security.SecKeychainGetStatus.restype = ctypes.c_int32
    core = ctypes.CDLL(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
    )
    core.CFRelease.argtypes = [ctypes.c_void_p]
    core.CFRelease.restype = None
    reference = ctypes.c_void_p()
    path = login_keychain()
    result = security.SecKeychainOpen(os.fsencode(path), ctypes.byref(reference))
    try:
        if result != 0 or not reference.value:
            raise KeychainUnavailable("keychain_status_failed", {"status": result})
        bits = ctypes.c_uint32()
        result = security.SecKeychainGetStatus(reference, ctypes.byref(bits))
        if result != 0:
            raise KeychainUnavailable("keychain_status_failed", {"status": result})
        return bits.value
    finally:
        if reference.value:
            core.CFRelease(reference)


def require_unlocked() -> None:
    if not keychain_status() & 1:  # kSecUnlockStateStatus
        raise KeychainUnavailable("keychain_locked")


def session_info() -> dict[str, int | bool]:
    security = ctypes.CDLL(SECURITY_FRAMEWORK)
    security.SessionGetInfo.argtypes = [
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    security.SessionGetInfo.restype = ctypes.c_int32
    session, attributes = ctypes.c_uint32(), ctypes.c_uint32()
    status = security.SessionGetInfo(
        0xFFFFFFFF, ctypes.byref(session), ctypes.byref(attributes)
    )
    return {
        "status": status,
        "session_id": session.value,
        "attributes": attributes.value,
        "graphic_access": bool(attributes.value & SESSION_HAS_GRAPHIC_ACCESS),
    }


def require_aqua() -> dict[str, int | bool]:
    if sys.platform != "darwin":
        raise KeychainUnavailable("host_not_macos")
    evidence = session_info()
    if evidence["status"] != 0 or not evidence["graphic_access"]:
        raise KeychainUnavailable("aqua_session_required", evidence)
    return evidence


def _security(arguments: list[str], *, timeout: float, cause: str) -> bytes:
    process = subprocess.Popen(
        ["/usr/bin/security", *arguments, str(login_keychain())],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        value, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise KeychainUnavailable(f"{cause}_timeout") from None
    except BaseException:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise
    if process.returncode != 0:
        raise KeychainUnavailable(f"{cause}_denied")
    if len(value) > 32 * 1024**2:
        raise KeychainUnavailable(f"{cause}_invalid")
    return value


def parse_storage_acl(output: bytes) -> dict[str, int | bool]:
    """Consume the complete target ACL, keeping metadata out of diagnostics."""
    try:
        blocks = re.split(r"(?=^keychain:)", output.decode("utf-8"), flags=re.M)
        targets = [
            block
            for block in blocks
            if re.search(r'^    "svce"<blob>="Chrome Safe Storage"$', block, re.M)
            and re.search(r'^    "acct"<blob>="Chrome"$', block, re.M)
        ]
        if len(targets) != 1:
            raise ValueError
        block = targets[0]
        if not re.search(r'^class: "genp"$', block, re.M):
            raise ValueError
        header = re.search(r"^access: ([0-9]+) entries\n", block, re.M)
        if header is None:
            raise ValueError
        entries = re.split(r"(?=^    entry [0-9]+:)", block[header.end() :], flags=re.M)
        entries = [entry for entry in entries if entry.strip()]
        if len(entries) != int(header[1]) or not entries:
            raise ValueError
        decrypt = partition = False
        for index, entry in enumerate(entries):
            match = re.fullmatch(
                rf"    entry {index}:\n"
                r"        authorizations \(([0-9]+)\): ([a-z_ ]+)\n"
                r"        (don't-require-password|require-password)\n"
                r"        description: ([^\n]*)\n"
                r"        applications(?:: <null>| \(([0-9]+)\):)\n(.*)",
                entry.rstrip("\n") + "\n",
                re.S,
            )
            if match is None:
                raise ValueError
            authorizations = match[2].split()
            if len(authorizations) != int(match[1]) or len(set(authorizations)) != len(
                authorizations
            ):
                raise ValueError
            apps = match[6]
            count = int(match[5]) if match[5] is not None else 0
            applications = re.findall(
                r"            ([0-9]+): ([^\n]+) \(([^\n]+)\)\n"
                r"                requirement: ([^\n]+)\n",
                apps,
            )
            rebuilt = "".join(
                f"            {number}: {path} ({status})\n"
                f"                requirement: {requirement}\n"
                for number, path, status, requirement in applications
            )
            if (
                rebuilt != apps
                or len(applications) != count
                or [int(app[0]) for app in applications] != list(range(count))
            ):
                raise ValueError
            if "decrypt" in authorizations:
                valid = match[3] == "don't-require-password" and any(
                    path == "/usr/bin/security"
                    and status == "OK"
                    and requirement
                    == 'identifier "com.apple.security" and anchor apple'
                    for _, path, status, requirement in applications
                )
                if not valid:
                    raise ValueError
                decrypt = True
            if "partition_id" in authorizations:
                parts = [part.strip() for part in match[4].split(",")]
                if not parts or any(
                    not re.fullmatch(r"[a-z-]+:[A-Za-z0-9]*", part) for part in parts
                ):
                    raise ValueError
                partition = "apple-tool:" in parts
        if not decrypt or not partition:
            raise ValueError
        return {
            "acl_valid": True,
            "acl_entries": len(entries),
            "security_decrypt": True,
            "apple_tool_partition": True,
            "password_not_required": True,
        }
    except (ValueError, UnicodeError, IndexError):
        raise KeychainUnavailable("keychain_acl_invalid") from None


def validate_storage_acl(timeout: float = 60) -> dict[str, int | bool]:
    require_aqua()
    return parse_storage_acl(
        _security(
            ["dump-keychain", "-a"], timeout=min(60, timeout), cause="keychain_acl"
        )
    )


def storage_password(timeout: float = 5) -> tuple[bytes, dict[str, int | bool]]:
    evidence = require_aqua()
    value = _security(
        ["find-generic-password", "-w", "-s", "Chrome Safe Storage", "-a", "Chrome"],
        timeout=min(5, timeout),
        cause="keychain_read",
    ).removesuffix(b"\n")
    if not 0 < len(value) <= 16384:
        raise KeychainUnavailable("keychain_read_invalid")
    return value, evidence
