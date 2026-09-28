"""Supervised host acquisition; container sessions own normal maintenance."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from app.core.db import create_engine, create_session_factory
from app.core.security.site_session_cipher import SiteSessionCipher
from app.integrations.site_session_catalog import site_target_for_host
from app.repositories.providers.site_sessions import (
    SiteSessionConflict,
    SiteSessionSecrets,
    SiteSessionStates,
)
from app.services.site_sessions import SiteSessionState
from app.workers.session.seed import (
    PROJECT_ROOT,
    SeedError,
    import_session,
    load_settings,
    select_seed,
    source_fingerprint,
)


def source_directory(env_file: Path) -> Path:
    identity = hashlib.sha256(str(env_file.resolve()).encode()).hexdigest()[:16]
    return Path.home() / "Library/Application Support/FrameFetch" / identity


async def reconcile_site(
    site: str,
    *,
    states: SiteSessionStates,
    secrets: SiteSessionSecrets,
    cipher: SiteSessionCipher,
    profile: str | None = None,
) -> str:
    current = await states.get(site)
    if current is not None and current.state is not SiteSessionState.RESEED_REQUIRED:
        return current.state.value
    stored = await secrets.read(site) if current is not None else None
    bound_profile = None if stored is None else stored.source_profile
    if bound_profile is not None and profile not in (None, bound_profile):
        return "profile_change_requires_import"
    target = site_target_for_host(site)
    choice = await asyncio.to_thread(
        select_seed, target, profile=bound_profile or profile
    )
    fingerprint = source_fingerprint(target, choice, cipher)
    if stored is not None and fingerprint == stored.source_fingerprint:
        return "awaiting_new_login"
    try:
        await import_session(
            target,
            choice,
            states=states,
            secrets=secrets,
            cipher=cipher,
            automatic=True,
            expected_seed_revision=0 if current is None else current.seed_revision,
            egress_route="default" if current is None else current.egress_route,
        )
    except SiteSessionConflict:
        return "changed_concurrently"
    return "imported_pending_verification"


def run_bounded(command: list[str], *, timeout: int, cwd: Path) -> tuple[int, str]:
    """Terminate the entire child group, including a blocked Keychain helper."""
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=timeout)
        return process.returncode, output.strip()
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        return 4, "source_timeout"


def reconcile(env_file: Path) -> dict[str, str]:
    settings = load_settings(env_file)
    directory = source_directory(env_file)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    request = directory / "access-request"
    request_id = request.read_text() if request.exists() else None
    access: dict[str, str] = {}
    results: dict[str, str] = {}
    for site in dict.fromkeys(settings.site_session_source_sites):
        _, result = run_bounded(
            [
                sys.executable,
                "-m",
                "app.workers.session.source",
                "site",
                "--env-file",
                str(env_file),
                "--site",
                site,
            ],
            timeout=60,
            cwd=PROJECT_ROOT / "backend",
        )
        results[site] = result or "source_unavailable"
        if request_id is not None:
            _, result = run_bounded(
                [
                    sys.executable,
                    "-m",
                    "app.workers.session.source",
                    "access",
                    "--env-file",
                    str(env_file),
                    "--site",
                    site,
                ],
                timeout=60,
                cwd=PROJECT_ROOT / "backend",
            )
            access[site] = result or "source_unavailable"
    payload: dict[str, object] = {
        "checked_at": datetime.now(UTC).isoformat(),
        "sites": results,
    }
    _write_status(directory / "source-status.json", payload)
    if request_id is not None:
        _write_status(
            directory / "access-status.json",
            {
                "request_id": request_id,
                "checked_at": datetime.now(UTC).isoformat(),
                "sites": access,
            },
        )
        if request.exists() and request.read_text() == request_id:
            request.unlink()
    return results


def _write_status(destination: Path, payload: dict[str, object]) -> None:
    # Only safe state codes leave the source process; no cookies or fingerprint.
    with tempfile.NamedTemporaryFile(
        mode="w", dir=destination.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        json.dump(payload, stream)
    temporary.replace(destination)


async def _site(env_file: Path, site: str, *, check_access: bool = False) -> str:
    settings = load_settings(env_file)
    if site not in settings.site_session_source_sites:
        return "site_not_enabled"
    key = settings.site_session_encryption_key
    if key is None:
        return "encryption_key_missing"
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    try:
        if check_access:
            current = await SiteSessionStates(sessions).get(site)
            if current is not None and current.state is SiteSessionState.REVOKED:
                return "revoked"
            stored = await SiteSessionSecrets(sessions).read(site)
            bound_profile = None if stored is None else stored.source_profile
            configured = settings.site_session_source_profiles.get(site)
            if bound_profile is not None and configured not in (None, bound_profile):
                return "profile_change_requires_import"
            await asyncio.to_thread(
                select_seed,
                site_target_for_host(site),
                profile=bound_profile or configured,
            )
            return "readable"
        return await reconcile_site(
            site,
            states=SiteSessionStates(sessions),
            secrets=SiteSessionSecrets(sessions),
            cipher=SiteSessionCipher(key.get_secret_value()),
            profile=settings.site_session_source_profiles.get(site),
        )
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("reconcile", "site", "access"))
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--site", choices=("youtube.com", "douyin.com"))
    args = parser.parse_args()
    try:
        if args.command in {"site", "access"}:
            if args.site is None:
                parser.error("site requires --site")
            print(
                asyncio.run(
                    _site(
                        args.env_file.resolve(),
                        args.site,
                        check_access=args.command == "access",
                    )
                )
            )
        else:
            print(json.dumps(reconcile(args.env_file.resolve())))
        return 0
    except SeedError as exc:
        print(
            {2: "login_or_profile_required", 3: "chrome_permission_required"}.get(
                int(exc.code), "source_unavailable"
            )
        )
        return int(exc.code)
    except Exception:
        # DB/config exceptions can contain connection secrets; never print them.
        print("source_unavailable")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
