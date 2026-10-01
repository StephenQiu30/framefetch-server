"""Read via a short-lived launchd user-domain job; never use a GUI fallback."""

from __future__ import annotations

import argparse
import base64
import ctypes
import json
import os
import plistlib
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

SECURITY_FRAMEWORK = "/System/Library/Frameworks/Security.framework/Security"
SESSION_HAS_GRAPHIC_ACCESS = 0x10


class KeychainUnavailable(Exception):
    def __init__(self, cause: str, evidence: dict[str, int | bool] | None = None):
        super().__init__(cause)
        self.cause = cause
        self.evidence = evidence or {}


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
    path = Path.home() / "Library/Keychains/login.keychain-db"
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


def read_in_child() -> tuple[bytes, dict[str, int | bool]]:
    """Called only inside the launchd job, before spawning /usr/bin/security."""
    evidence = session_info()
    if evidence["status"] != 0 or evidence["graphic_access"]:
        raise KeychainUnavailable("graphic_session_refused", evidence)
    command = [
        "/usr/bin/security",
        "find-generic-password",
        "-w",
        "-s",
        "Chrome Safe Storage",
        "-a",
        "Chrome",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        value, _ = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise KeychainUnavailable("keychain_read_timeout", evidence) from None
    except BaseException:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise
    if process.returncode != 0:
        raise KeychainUnavailable("keychain_read_denied", evidence)
    value = value.removesuffix(b"\n")
    if not 0 < len(value) <= 16384:
        raise KeychainUnavailable("keychain_read_invalid", evidence)
    return value, evidence


def launchd_storage_password(timeout: float) -> tuple[bytes, dict[str, int | bool]]:
    """A private local socket carries the key; no secret files or arguments."""
    if sys.platform != "darwin":
        raise KeychainUnavailable("host_not_macos")
    end = time.monotonic() + timeout
    label = f"com.framefetch.key-read.{uuid4().hex}"
    target = f"user/{os.getuid()}"
    with tempfile.TemporaryDirectory(prefix="ff-key-", dir="/tmp") as folder:
        root = Path(folder)
        endpoint = root / "pipe"
        plist = root / "job.plist"
        job = {
            "Label": label,
            "ProgramArguments": [
                sys.executable,
                "-m",
                "app.workers.identity.keychain",
                "--socket",
                str(endpoint),
            ],
            "WorkingDirectory": str(Path(__file__).resolve().parents[3]),
            "SessionCreate": True,
            "LimitLoadToSessionType": "Background",
            "RunAtLoad": True,
            "StandardOutPath": "/dev/null",
            "StandardErrorPath": "/dev/null",
        }
        plist.write_bytes(plistlib.dumps(job))
        plist.chmod(0o600)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(endpoint))
            endpoint.chmod(0o600)
            server.listen(1)
            try:
                result = subprocess.run(
                    ["/bin/launchctl", "bootstrap", target, str(plist)],
                    capture_output=True,
                    timeout=min(3, timeout),
                )
                if result.returncode != 0:
                    raise KeychainUnavailable("launchd_user_domain_unavailable")
                server.settimeout(max(0.001, end - time.monotonic()))
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(max(0.001, end - time.monotonic()))
                    chunks = bytearray()
                    while True:
                        connection.settimeout(max(0.001, end - time.monotonic()))
                        data = connection.recv(4096)
                        if not data:
                            break
                        chunks.extend(data)
                        if len(chunks) > 32768:
                            raise KeychainUnavailable("keychain_read_invalid")
                response = json.loads(chunks)
                evidence = response["session"]
                if response["cause"]:
                    raise KeychainUnavailable(response["cause"], evidence)
                # Validate the child attestation again; no graphical-session fallback.
                if evidence["status"] != 0 or evidence["graphic_access"]:
                    raise KeychainUnavailable("graphic_session_refused", evidence)
                password = base64.b64decode(response["password"], validate=True)
                if not 0 < len(password) <= 16384:
                    raise KeychainUnavailable("keychain_read_invalid", evidence)
                return password, evidence
            except (TimeoutError, subprocess.TimeoutExpired):
                raise KeychainUnavailable("keychain_read_timeout") from None
            finally:
                subprocess.run(
                    ["/bin/launchctl", "bootout", f"{target}/{label}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    args = parser.parse_args()

    # launchctl bootout must terminate the security subprocess group as well.
    def terminated(signum: int, frame: object) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminated)
    response: dict[str, object]
    try:
        value, evidence = read_in_child()
        response = {
            "cause": None,
            "session": evidence,
            "password": base64.b64encode(value).decode("ascii"),
        }
    except KeychainUnavailable as error:
        response = {"cause": error.cause, "session": error.evidence}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
        channel.settimeout(2)
        channel.connect(args.socket)
        channel.sendall(json.dumps(response).encode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
