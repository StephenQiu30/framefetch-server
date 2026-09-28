"""Refresh deployment-owned provider sources from the host user's browser."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from app.core.config import Settings
from app.core.db import create_engine, create_session_factory
from app.core.security.provider_session_cipher import ProviderSessionCipher
from app.repositories.providers.session_sources import (
    ProviderSessionSources,
    SourceRevisionConflict,
)
from app.services.provider_types import ProviderKey
from app.workers.runner._secure_file import (
    atomic_write_json,
    ensure_private_directory,
    read_private_json,
    validate_private_file,
)
from app.workers.runner.provider_cookie_boundary import (
    export_provider_cookie_lease_bounded,
)
from app.workers.runner.provider_cookie_lease import (
    ProviderCookieLease,
    ProviderCookieLeaseStatus,
)
from app.workers.runner.provider_session_policy import (
    ProviderSessionSource,
    browser_session_policy,
)
from app.workers.session.chrome_reader import DEFAULT_CHROME_ROOT
from cryptography.fernet import InvalidToken
from dotenv import dotenv_values

SOURCE_VALID_FOR = timedelta(minutes=15)
REFRESH_BEFORE = timedelta(minutes=5)
REFRESH_INTERVAL_SECONDS = 60
MAX_PROFILES = 16
SOURCE_OWNER_HEADER = b"# FrameFetch source owner: host-browser\n"
SERVICE_ID = "com.framefetch.provider-source-host"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_ID}.plist"
BACKEND_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_DIR = BACKEND_ROOT / ".local-runtime"
STATUS_PATH = RUNTIME_DIR / "provider-source-host-status.json"
PID_PATH = STATUS_PATH.with_name("provider-source-host.pid.json")
START_LOCK_PATH = STATUS_PATH.with_name("provider-source-host-start.lock")


def browser_profiles(root: Path = DEFAULT_CHROME_ROOT) -> tuple[str, ...]:
    """Only consider ordinary, bounded Chrome profiles; never follow a profile link."""
    if not root.is_dir() or root.is_symlink():
        return ()
    names = ("Default", *(f"Profile {index}" for index in range(1, MAX_PROFILES)))
    return tuple(
        name
        for name in names
        if (root / name).is_dir() and not (root / name).is_symlink()
    )


def select_source(
    provider: ProviderKey,
    *,
    root: Path = DEFAULT_CHROME_ROOT,
    export: Callable[..., ProviderCookieLease] = export_provider_cookie_lease_bounded,
) -> tuple[str, bytes | None]:
    policy = browser_session_policy(provider)
    if policy.source is not ProviderSessionSource.CHROME_PROFILE:
        return "unsupported_source", None
    profiles = browser_profiles(root)
    if not profiles:
        return "browser_login_missing", None
    candidates: list[bytes] = []
    denied = False
    unavailable = False
    with ThreadPoolExecutor(max_workers=min(len(profiles), 8)) as pool:
        futures = tuple(
            pool.submit(
                export,
                provider=provider,
                profile=profile,
                version=policy.version,
                chrome_root=root,
            )
            for profile in profiles
        )
        leases = tuple(future.result() for future in futures)
    for lease in leases:
        if lease.status is ProviderCookieLeaseStatus.OK:
            assert lease.payload is not None
            candidates.append(lease.payload)
        elif lease.status is ProviderCookieLeaseStatus.PERMISSION_DENIED:
            denied = True
        elif lease.status is ProviderCookieLeaseStatus.SESSION_UNAVAILABLE:
            unavailable = True
    if len(candidates) > 1:
        return "browser_source_ambiguous", None
    if denied:
        return "browser_permission_denied", None
    if unavailable:
        return "browser_source_unavailable", None
    if not candidates:
        return "browser_login_missing", None
    return "candidate", candidates[0]


class HostBrowserSourceSync:
    def __init__(
        self,
        sources: ProviderSessionSources,
        cipher: ProviderSessionCipher,
        *,
        select: Callable[[ProviderKey], tuple[str, bytes | None]] = select_source,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sources = sources
        self._cipher = cipher
        self._select = select
        self._clock = clock or (lambda: datetime.now(UTC))

    async def sync(self, provider: ProviderKey) -> str:
        state, payload = await asyncio.to_thread(self._select, provider)
        for _ in range(3):
            row = await self._sources.read(provider)
            revision = row.revision if row is not None else 0
            existing: bytes | None = None
            if row is not None and row.ciphertext is not None and row.valid_until:
                try:
                    existing = self._cipher.decrypt(
                        provider, revision, row.valid_until, row.ciphertext
                    )
                except (ValueError, InvalidToken):
                    return "source_sync_unavailable"
                if SOURCE_OWNER_HEADER not in existing.splitlines(keepends=True):
                    return "manual_source_preserved"
            if payload is None:
                if row is None or row.ciphertext is None:
                    return state
                if state not in {"browser_login_missing", "browser_source_ambiguous"}:
                    return state
                try:
                    await self._sources.publish(
                        provider,
                        expected_revision=revision,
                        ciphertext=None,
                        valid_until=None,
                    )
                    return state
                except SourceRevisionConflict:
                    continue
            assert payload is not None
            header, body = payload.split(b"\n", 1)
            owned_payload = header + b"\n" + SOURCE_OWNER_HEADER + body
            if (
                existing == owned_payload
                and row is not None
                and row.valid_until is not None
                and row.valid_until > self._clock() + REFRESH_BEFORE
            ):
                return "ready"
            expiry = self._clock() + SOURCE_VALID_FOR
            ciphertext = self._cipher.encrypt(
                provider, revision + 1, expiry, owned_payload
            )
            try:
                await self._sources.publish(
                    provider,
                    expected_revision=revision,
                    ciphertext=ciphertext,
                    valid_until=expiry,
                )
                return "ready"
            except SourceRevisionConflict:
                continue
        return "source_sync_unavailable"


def load_settings(
    env_file: Path, overrides: Mapping[str, str] | None = None
) -> Settings:
    values: dict[str, str] = {
        key.lower(): value
        for key, value in dotenv_values(env_file).items()
        if value is not None
    }
    values.update({key.lower(): value for key, value in (overrides or {}).items()})
    required = {
        key: values[key]
        for key in ("database_url", "provider_source_encryption_key")
        if key in values
    }
    return Settings(
        _env_file=None,
        service_role="provider-sources",
        **cast(dict[str, Any], required),
    )


async def sync_once(provider: ProviderKey, settings: Settings) -> str:
    key = settings.provider_source_encryption_key
    if key is None:
        return "source_sync_unavailable"
    engine = create_engine(settings.database_url)
    try:
        sync = HostBrowserSourceSync(
            ProviderSessionSources(create_session_factory(engine)),
            ProviderSessionCipher(key.get_secret_value()),
        )
        return await asyncio.wait_for(sync.sync(provider), timeout=45)
    finally:
        await engine.dispose()


def disable_launch_agent() -> None:
    """Retire the old launchd reader after its replacement is running."""
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{SERVICE_ID}"
    current = subprocess.run(
        ("launchctl", "print", service), capture_output=True, check=False
    )
    if current.returncode == 0:
        subprocess.run(("launchctl", "bootout", service), check=True)
    PLIST_PATH.unlink(missing_ok=True)


def _owned_detached_pid() -> int | None:
    document = read_private_json(PID_PATH, message="unsafe host source PID file")
    if not isinstance(document, dict):
        return None
    pid = document.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid < 2:
        return None
    result = subprocess.run(
        ("ps", "-p", str(pid), "-o", "uid=", "-o", "command="),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    line = result.stdout.strip()
    uid, _, command = line.partition(" ")
    if uid.strip() != str(os.getuid()) or (
        "-m app.workers.runner.provider_source_host serve" not in command
    ):
        return None
    return pid


def start_detached_source_service(
    *,
    env_file: Path,
    providers: tuple[ProviderKey, ...],
    source_key: str,
) -> dict[str, str]:
    """Keep the browser reader in the authorized startup process context."""
    if sys.platform != "darwin":
        raise OSError("host browser source service requires macOS")
    ensure_private_directory(STATUS_PATH.parent)
    lock = os.open(
        START_LOCK_PATH, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    try:
        validate_private_file(lock, "unsafe host source start lock")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old_pid = _owned_detached_pid()
        if old_pid is not None:
            try:
                os.kill(old_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            for _ in range(40):
                if _owned_detached_pid() is None:
                    break
                time.sleep(0.25)
            else:
                if _owned_detached_pid() == old_pid:
                    os.kill(old_pid, signal.SIGKILL)
        command = [
            str(Path(sys.executable).absolute()),
            "-m",
            "app.workers.runner.provider_source_host",
            "serve",
            "--env-file",
            str(env_file.absolute()),
            "--status-file",
            str(STATUS_PATH),
        ]
        for provider in providers:
            command.extend(("--provider", provider.value))
        environment = os.environ.copy()
        environment["PROVIDER_SOURCE_ENCRYPTION_KEY"] = source_key
        process = subprocess.Popen(
            command,
            cwd=Path(__file__).resolve().parents[3],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        atomic_write_json(PID_PATH, {"pid": process.pid})
        try:
            for _ in range(200):
                document = read_private_json(
                    STATUS_PATH, message="unsafe host source status file"
                )
                if isinstance(document, dict) and document.get("pid") == process.pid:
                    states = document.get("states")
                    if isinstance(states, dict) and all(
                        isinstance(key, str) and isinstance(value, str)
                        for key, value in states.items()
                    ):
                        return states
                if process.poll() is not None:
                    raise RuntimeError("host browser source service exited at startup")
                time.sleep(0.25)
            raise TimeoutError("host browser source service did not report status")
        except BaseException:
            if process.poll() is None:
                process.terminate()
            PID_PATH.unlink(missing_ok=True)
            raise
    finally:
        os.close(lock)


def write_status(
    path: Path,
    states: dict[str, str],
    *,
    checked_at: datetime | None = None,
    pid: int | None = None,
) -> None:
    ensure_private_directory(path.parent)
    atomic_write_json(
        path,
        {
            "checked_at": (checked_at or datetime.now(UTC)).isoformat(),
            "pid": os.getpid() if pid is None else pid,
            "states": states,
        },
    )


async def run(
    providers: tuple[ProviderKey, ...],
    settings: Settings,
    *,
    serve: bool,
    status_file: Path | None = None,
) -> int:
    key = settings.provider_source_encryption_key
    if key is None:
        print("provider source host: encryption key missing")
        return 2
    engine = create_engine(settings.database_url)
    sync = HostBrowserSourceSync(
        ProviderSessionSources(create_session_factory(engine)),
        ProviderSessionCipher(key.get_secret_value()),
    )
    stop = asyncio.Event()
    if serve:
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, stop.set)
    try:
        while not stop.is_set():
            states: dict[str, str] = {}
            for provider in providers:
                try:
                    state = await asyncio.wait_for(sync.sync(provider), timeout=45)
                except Exception:
                    state = "source_sync_unavailable"
                states[provider.value] = state
                print(f"{provider.value}: {state}", flush=True)
            if status_file is not None:
                write_status(status_file, states)
            if not serve:
                break
            try:
                await asyncio.wait_for(stop.wait(), timeout=REFRESH_INTERVAL_SECONDS)
            except TimeoutError:
                pass
    finally:
        await engine.dispose()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="自动维护宿主浏览器的单平台加密来源")
    parser.add_argument("command", choices=("once", "serve"))
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--provider", type=ProviderKey, action="append", required=True)
    parser.add_argument("--status-file", type=Path)
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        print("provider source host: unsupported host browser adapter")
        return 2
    settings = load_settings(args.env_file, os.environ)
    return asyncio.run(
        run(
            tuple(dict.fromkeys(args.provider)),
            settings,
            serve=args.command == "serve",
            status_file=args.status_file,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
