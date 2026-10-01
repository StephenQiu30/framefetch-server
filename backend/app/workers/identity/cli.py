"""Host run/install/uninstall/doctor entrypoint; launchd user domain only."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import plistlib
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import CookieSourceSettings
from app.workers.identity.keychain import (
    KeychainUnavailable,
    keychain_status,
    launchd_storage_password,
    require_unlocked,
)

LABEL = "com.framefetch.cookie-source"


def agent_path() -> Path:
    return Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"


def agent_spec(env_file: Path) -> dict[str, object]:
    return {
        "Label": LABEL,
        "ProgramArguments": [
            sys.executable,
            "-m",
            "app.workers.identity.cli",
            "run",
            "--env-file",
            str(env_file),
        ],
        "WorkingDirectory": str(Path(__file__).resolve().parents[3]),
        "RunAtLoad": True,
        "KeepAlive": True,
        "SessionCreate": True,
        "LimitLoadToSessionType": "Background",
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
    }


def install(env_file: Path) -> None:
    configured(env_file)
    destination = agent_path()
    if destination.exists():
        raise ValueError("cookie_source_already_installed")
    destination.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(destination, flags, 0o600), "wb") as stream:
        plistlib.dump(agent_spec(env_file), stream)
    try:
        subprocess.run(
            ["/bin/launchctl", "bootstrap", f"user/{os.getuid()}", str(destination)],
            check=True,
            capture_output=True,
            timeout=5,
        )
    except Exception:
        destination.unlink()
        raise


def uninstall() -> None:
    target = f"user/{os.getuid()}/{LABEL}"
    result = subprocess.run(
        ["/bin/launchctl", "bootout", target], capture_output=True, timeout=5
    )
    if result.returncode != 0:
        status = subprocess.run(
            ["/bin/launchctl", "print", target], capture_output=True, timeout=5
        )
        if status.returncode == 0:
            raise ValueError("cookie_source_uninstall_failed")
    agent_path().unlink(missing_ok=True)


def configured(env_file: Path) -> CookieSourceSettings:
    metadata = env_file.stat()
    if (
        not env_file.is_file()
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
    ):
        raise ValueError("cookie_source_env_requires_owner_only_permissions")
    return CookieSourceSettings(_env_file=env_file)


async def doctor(settings: CookieSourceSettings) -> int:
    from app.workers.identity.cookie_source import CookieRequest, CookieSource

    result: dict[str, object] = {
        "profile_exists": settings.cookie_source_chrome_profile.is_dir()
    }
    try:
        result["keychain_status_bits"] = keychain_status()
        require_unlocked()
        _, result["child_session"] = await asyncio.to_thread(
            launchd_storage_password, 10
        )
        result["key_read"] = "succeeded"
        source = CookieSource(settings)
        sites: dict[str, str] = {}
        for site in ("instagram", "qqvideo"):
            try:
                await source.cookies(
                    CookieRequest(
                        site=site,
                        task_id="identity-doctor",
                        deadline=datetime.now(UTC) + timedelta(seconds=30),
                    )
                )
                sites[site] = "material_available_not_platform_acceptance"
            except KeychainUnavailable as error:
                sites[site] = error.cause
        result["sites"] = sites
        code = 0
    except KeychainUnavailable as error:
        result["key_read"] = error.cause
        result["child_session"] = error.evidence
        code = 2
    print(json.dumps(result, ensure_ascii=False))
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="帧取宿主身份服务（禁止图形会话回退）")
    parser.add_argument("command", choices=("run", "install", "uninstall", "doctor"))
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    if sys.platform != "darwin":
        print("cookie-source requires macOS", file=sys.stderr)
        return 2
    try:
        if args.command == "uninstall":
            uninstall()
            return 0
        if args.env_file is None:
            raise ValueError("cookie_source_env_file_required")
        env_file = args.env_file.expanduser().resolve()
        settings = configured(env_file)
        if args.command == "install":
            install(env_file)
        elif args.command == "doctor":
            return asyncio.run(doctor(settings))
        else:
            import uvicorn
            from app.workers.identity.cookie_source import create_app

            uvicorn.run(
                create_app(settings),
                host="127.0.0.1",
                port=settings.cookie_source_port,
                access_log=False,
                log_level="critical",
                limit_concurrency=4,
            )
    except Exception:
        print("cookie-source operation failed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
