"""Install the unpacked MV3 extension and ordinary per-user LaunchAgent."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import plistlib
import secrets
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

import httpx
from app.core.config import CookieSourceSettings
from app.workers.identity.extension import (
    extension_home,
    install_extension,
    private_directory,
    private_write,
)
from dotenv import dotenv_values
from pydantic import SecretStr

LABEL = "com.framefetch.cookie-source"


def agent_path() -> Path:
    return Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"


def default_env_file() -> Path:
    return Path.home() / "Library/Application Support/Framefetch/identity.env"


def agent_spec(env_file: Path) -> dict[str, object]:
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(extension_home().parent / "backend/.venv/bin/python"),
            "-m",
            "app.workers.identity.cli",
            "run",
            "--env-file",
            str(env_file),
        ],
        "WorkingDirectory": str(extension_home().parent / "backend"),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
        "Umask": 0o077,
    }


def configured(env_file: Path) -> CookieSourceSettings:
    metadata = env_file.lstat()
    if (
        env_file.is_symlink()
        or not env_file.is_file()
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
    ):
        raise ValueError("cookie_source_env_requires_owner_only_permissions")
    return CookieSourceSettings(_env_file=env_file)


def prepare_config(env_file: Path) -> CookieSourceSettings:
    # Never edit the project's .env. The host identity config is separate.
    if env_file.name in {".env", ".env.prod"}:
        raise ValueError("cookie_source_requires_separate_env_file")
    if env_file.exists() or env_file.is_symlink():
        metadata = env_file.lstat()
        if (
            env_file.is_symlink()
            or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o077
        ):
            raise ValueError("cookie_source_env_requires_owner_only_permissions")
        values = dotenv_values(env_file)
        if values.get("COOKIE_SOURCE_PAIRING_KEY"):
            return configured(env_file)
        # Upgrade a separately supplied token-only identity config; preserve it.
        content = env_file.read_text().rstrip() + "\n"
    else:
        private_directory(env_file.parent)
        token = os.environ.get("COOKIE_SOURCE_TOKEN") or secrets.token_urlsafe(48)
        content = f"COOKIE_SOURCE_TOKEN={token}\nCOOKIE_SOURCE_PORT=19101\n"
    content += f"COOKIE_SOURCE_PAIRING_KEY={secrets.token_urlsafe(48)}\n"
    # Validate before writing (including independence from the Runner token).
    values = dotenv_values(stream=io.StringIO(content))
    settings = CookieSourceSettings(
        cookie_source_token=SecretStr(values["COOKIE_SOURCE_TOKEN"] or ""),
        cookie_source_pairing_key=SecretStr(values["COOKIE_SOURCE_PAIRING_KEY"] or ""),
        cookie_source_port=int(values.get("COOKIE_SOURCE_PORT") or 19101),
    )
    private_write(env_file, content)
    return settings


def install(env_file: Path) -> Path:
    settings = prepare_config(env_file)
    if secrets.compare_digest(
        settings.cookie_source_token.get_secret_value(),
        settings.cookie_source_pairing_key.get_secret_value(),
    ):
        raise ValueError("pairing_key_must_differ_from_runner_token")
    extension = install_extension(settings)
    destination = agent_path()
    target = f"gui/{os.getuid()}/{LABEL}"
    if destination.exists():
        metadata = destination.lstat()
        if destination.is_symlink() or metadata.st_uid != os.getuid():
            raise ValueError("cookie_source_agent_owner")
        spec = plistlib.loads(destination.read_bytes())
        if spec.get("Label") != LABEL:
            raise ValueError("cookie_source_agent_invalid")
        # This label belongs to cookie-source; upgrades restart only this agent.
        uninstall()
    destination.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(destination, flags, 0o600), "wb") as stream:
        plistlib.dump(agent_spec(env_file), stream)
    try:
        subprocess.run(
            ["/bin/launchctl", "bootstrap", f"gui/{os.getuid()}", str(destination)],
            check=True,
            capture_output=True,
            timeout=5,
        )
        subprocess.run(
            ["/bin/launchctl", "kickstart", target],
            check=True,
            capture_output=True,
            timeout=5,
        )
    except Exception:
        with suppress(Exception):
            uninstall()
        destination.unlink(missing_ok=True)
        raise
    return extension


def uninstall() -> None:
    target = f"gui/{os.getuid()}/{LABEL}"
    result = subprocess.run(
        ["/bin/launchctl", "bootout", "--wait", target],
        capture_output=True,
        timeout=5,
    )
    if result.returncode != 0:
        status = subprocess.run(
            ["/bin/launchctl", "print", target], capture_output=True, timeout=5
        )
        if status.returncode == 0:
            raise ValueError("cookie_source_uninstall_failed")
    agent_path().unlink(missing_ok=True)


async def check(settings: CookieSourceSettings) -> int:
    async with httpx.AsyncClient(
        trust_env=False, follow_redirects=False, timeout=2
    ) as client:
        token = settings.cookie_source_token.get_secret_value()
        response = await client.get(
            f"http://127.0.0.1:{settings.cookie_source_port}/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        result = response.json()
        print(
            json.dumps({"connected": result["connected"], "version": result["version"]})
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="帧取宿主身份服务与 Chrome 扩展")
    parser.add_argument("command", choices=("run", "install", "uninstall", "check"))
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    if sys.platform != "darwin":
        print("cookie-source requires macOS", file=sys.stderr)
        return 2
    try:
        if args.command == "uninstall":
            uninstall()
            return 0
        env_file = (args.env_file or default_env_file()).expanduser().absolute()
        if args.command == "install":
            print(install(env_file))
        else:
            settings = configured(env_file)
            if args.command == "check":
                return asyncio.run(check(settings))
            import uvicorn
            from app.workers.identity.cookie_source import create_app
            from app.workers.identity.yuanbao_parse import (
                YUANBAO_PARSE_MAX_MESSAGE_BYTES,
            )

            uvicorn.run(
                create_app(settings),
                host="127.0.0.1",
                port=settings.cookie_source_port,
                access_log=False,
                log_level="critical",
                limit_concurrency=8,
                ws_max_size=YUANBAO_PARSE_MAX_MESSAGE_BYTES,
                ws_max_queue=4,
            )
    except Exception:
        print("cookie-source operation failed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
