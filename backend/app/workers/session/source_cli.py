"""Run or install the host's automatic, fixed-profile Chrome session source."""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import plistlib
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import uvicorn
from app.integrations.site_session_catalog import known_session_sites
from app.workers.session.chrome_source import ChromeSource
from app.workers.session.contracts import STATUS_PATH, StatusRequest, StatusResponse
from app.workers.session.rpc import RpcError, SignedClient
from app.workers.session.source_app import create_app
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SOURCE_PORT = 19250
SOURCE_LABEL = "com.framefetch.browser-source"


@dataclass(frozen=True, slots=True)
class SourceConfig:
    secret: bytes = field(repr=False)
    chrome_profile: Path
    read_timeout_seconds: float = 15.0


def load_config(env_file: Path | None) -> SourceConfig:
    names = (
        "SITE_SESSION_AGENT_SECRET",
        "SITE_SESSION_CHROME_PROFILE",
        "SITE_SESSION_READ_TIMEOUT_SECONDS",
    )
    values = dict(dotenv_values(env_file)) if env_file else {}
    values.update({name: os.environ[name] for name in names if name in os.environ})
    secret = (
        values.get("SITE_SESSION_AGENT_SECRET")
        or "development-site-session-agent-secret-change-me"
    ).encode()
    if len(secret) < 32:
        raise SystemExit("SITE_SESSION_AGENT_SECRET must contain at least 32 bytes")
    profile = Path(
        values.get("SITE_SESSION_CHROME_PROFILE")
        or str(Path.home() / "Library/Application Support/Google/Chrome/Default")
    ).expanduser()
    if not profile.is_absolute():
        raise SystemExit("SITE_SESSION_CHROME_PROFILE must be absolute")
    try:
        timeout = float(values.get("SITE_SESSION_READ_TIMEOUT_SECONDS") or "15")
    except ValueError:
        raise SystemExit("SITE_SESSION_READ_TIMEOUT_SECONDS must be a number") from None
    if not math.isfinite(timeout) or not 1 <= timeout <= 60:
        raise SystemExit("SITE_SESSION_READ_TIMEOUT_SECONDS must be between 1 and 60")
    return SourceConfig(secret, profile, timeout)


def agent_spec(config: SourceConfig) -> dict[str, object]:
    # No database, queue, object-store, AI or application-login credentials.
    return {
        "Label": SOURCE_LABEL,
        "ProgramArguments": [
            sys.executable,
            "-m",
            "app.workers.session.source_cli",
            "serve",
        ],
        "WorkingDirectory": str(PROJECT_ROOT / "backend"),
        "EnvironmentVariables": {
            "SITE_SESSION_AGENT_SECRET": config.secret.decode(),
            "SITE_SESSION_CHROME_PROFILE": str(config.chrome_profile),
            "SITE_SESSION_READ_TIMEOUT_SECONDS": str(config.read_timeout_seconds),
            "PATH": os.defpath,
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "ProcessType": "Interactive",
        "Umask": 0o077,
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
    }


def launchctl(*args: str, check: bool = True) -> None:
    subprocess.run(
        ["/bin/launchctl", *args],
        check=check,
        timeout=15,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def install(config: SourceConfig) -> None:
    directory = Path.home() / "Library/LaunchAgents"
    directory.mkdir(parents=True, exist_ok=True)
    old_label = "com.framefetch.chrome-agent"
    launchctl("bootout", f"gui/{os.getuid()}/{old_label}", check=False)
    (directory / f"{old_label}.plist").unlink(missing_ok=True)
    launchctl("bootout", f"gui/{os.getuid()}/{SOURCE_LABEL}", check=False)
    destination = directory / f"{SOURCE_LABEL}.plist"
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
        stream.write(plistlib.dumps(agent_spec(config)))
        temporary = Path(stream.name)
    temporary.chmod(0o600)
    temporary.replace(destination)
    # launchd can briefly retain a booted-out job; only retry that EIO result.
    for attempt in range(8):
        try:
            launchctl("bootstrap", f"gui/{os.getuid()}", str(destination))
            break
        except subprocess.CalledProcessError as error:
            if error.returncode != 5 or attempt == 7:
                raise SystemExit(
                    "Chrome source installation failed; "
                    "launchd did not accept the service"
                ) from None
            time.sleep(0.5 * (attempt + 1))


def uninstall() -> None:
    launchctl("bootout", f"gui/{os.getuid()}/{SOURCE_LABEL}", check=False)
    (Path.home() / "Library/LaunchAgents" / f"{SOURCE_LABEL}.plist").unlink(
        missing_ok=True
    )


async def control(config: SourceConfig, site: str | None) -> int:
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{SOURCE_PORT}",
        timeout=config.read_timeout_seconds + 5,
        trust_env=False,
    ) as http:
        client = SignedClient(http, config.secret)
        failed = False
        for target in (site,) if site else known_session_sites():
            try:
                await client.post(
                    STATUS_PATH, StatusRequest(site=target), StatusResponse
                )
                print(f"{target}\tsource_ready (platform acceptance not verified)")
            except RpcError as error:
                print(f"{target}\t{error.code}")
                failed = True
        return 2 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Automatic Chrome session source")
    parser.add_argument("command", choices=("serve", "install", "uninstall", "check"))
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--site", choices=known_session_sites())
    args = parser.parse_args()
    if args.site is not None and args.command != "check":
        parser.error("--site is only supported by check")
    if args.command == "uninstall":
        uninstall()
        return 0
    config = load_config(args.env_file)
    if args.command == "install":
        if sys.platform != "darwin":
            raise SystemExit("LaunchAgent installation requires macOS")
        install(config)
        print("Chrome source installed for automatic startup.")
        return 0
    if args.command == "check":
        return asyncio.run(control(config, args.site))
    source = ChromeSource(
        secret=config.secret,
        profile=config.chrome_profile,
        read_timeout_seconds=config.read_timeout_seconds,
    )
    uvicorn.run(
        create_app(source=source, secret=config.secret),
        host="127.0.0.1",
        port=SOURCE_PORT,
        access_log=False,
        timeout_graceful_shutdown=5,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
