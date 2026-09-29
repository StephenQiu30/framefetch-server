"""Install the Chrome extension and its local Python native messaging source."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import plistlib
import shlex
import shutil
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
from app.workers.session.contracts import (
    LOGIN_PATH,
    STATUS_PATH,
    LoginRequest,
    LoginResponse,
    StatusRequest,
    StatusResponse,
)
from app.workers.session.native_host import HOST_NAME
from app.workers.session.rpc import RpcError, SignedClient
from app.workers.session.source_app import create_app
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SOURCE_PORT = 19250
SOURCE_LABEL = "com.framefetch.browser-source"


@dataclass(frozen=True, slots=True)
class SourceConfig:
    secret: bytes = field(repr=False)
    root: Path


def load_config(env_file: Path | None) -> SourceConfig:
    values = dict(dotenv_values(env_file)) if env_file else {}
    values.update(
        {
            key: value
            for key, value in os.environ.items()
            if key.startswith("SITE_SESSION_")
        }
    )
    secret = (
        values.get("SITE_SESSION_AGENT_SECRET")
        or "development-site-session-agent-secret-change-me"
    )
    if len(secret.encode()) < 32:
        raise SystemExit("SITE_SESSION_AGENT_SECRET must contain at least 32 bytes")
    root = Path(
        values.get("SITE_SESSION_PROFILE_ROOT")
        or str(Path.home() / "Library/Application Support/FrameFetch/Browsers")
    ).expanduser()
    if not root.is_absolute():
        raise SystemExit("SITE_SESSION_PROFILE_ROOT must be absolute")
    return SourceConfig(secret.encode(), root)


def agent_spec(config: SourceConfig) -> dict[str, object]:
    # The long-lived process receives only source configuration,
    # never the database, AI, object-store, queue, or application login secrets.
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
            "SITE_SESSION_PROFILE_ROOT": str(config.root),
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
    # Retire the old host service only; never remove the user's Chrome data.
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
    install_extension(config)
    # bootout may return before launchd has fully detached the previous job.
    # Retry only the transient bootstrap EIO; never rewrite profiles or keys.
    for attempt in range(8):
        try:
            launchctl("bootstrap", f"gui/{os.getuid()}", str(destination))
            break
        except subprocess.CalledProcessError as error:
            if error.returncode != 5 or attempt == 7:
                raise SystemExit(
                    "Browser source installation failed; "
                    "launchd did not accept the service"
                ) from None
            time.sleep(0.5 * (attempt + 1))


def install_extension(config: SourceConfig) -> None:
    from urllib.parse import urlsplit

    from app.integrations.site_session_catalog import site_target
    from app.workers.runner.provider_session_files import prepare_private_root

    prepare_private_root(config.root)
    extension = config.root / "ChromeExtension"
    prepare_private_root(extension)
    assets = PROJECT_ROOT / "browser-extension"
    manifest = json.loads((assets / "manifest.json").read_text())
    domains: set[str] = set()
    for site in known_session_sites():
        target = site_target(site)
        domains.update(d.lstrip(".") for d in target.cookie_domains)
        host = urlsplit(target.policy.login_url).hostname
        assert host is not None
        domains.add(host)
    manifest["host_permissions"] = [f"https://*.{d}/*" for d in sorted(domains)]
    for name in ("background.js", "popup.html", "popup.js", "popup.css"):
        shutil.copyfile(assets / name, extension / name)
    (extension / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )
    digest = hashlib.sha256(base64.b64decode(manifest["key"])).hexdigest()[:32]
    extension_id = "".join(chr(ord("a") + int(char, 16)) for char in digest)
    origin = f"chrome-extension://{extension_id}/"
    private_config = config.root / "native-config.json"
    with tempfile.NamedTemporaryFile(dir=config.root, delete=False) as stream:
        stream.write(
            json.dumps({"secret": config.secret.decode(), "origin": origin}).encode()
        )
        temporary = Path(stream.name)
    temporary.chmod(0o600)
    temporary.replace(private_config)
    launcher = config.root / "native-host"
    launcher.write_text(
        "#!/bin/sh\n"
        + "cd "
        + shlex.quote(str(PROJECT_ROOT / "backend"))
        + " || exit 2\n"
        + "exec "
        + shlex.quote(sys.executable)
        + " -m app.workers.session.native_host --config "
        + shlex.quote(str(private_config))
        + ' "$@"\n'
    )
    launcher.chmod(0o700)
    host_manifest = {
        "name": HOST_NAME,
        "description": "FrameFetch Chrome session source",
        "path": str(launcher),
        "type": "stdio",
        "allowed_origins": [origin],
    }
    for browser in ("Chrome", "ChromeForTesting"):
        directory = (
            Path.home()
            / f"Library/Application Support/Google/{browser}/NativeMessagingHosts"
        )
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{HOST_NAME}.json"
        destination.write_text(json.dumps(host_manifest))
        destination.chmod(0o600)


def uninstall() -> None:
    for browser in ("Chrome", "ChromeForTesting"):
        (
            Path.home()
            / f"Library/Application Support/Google/{browser}/NativeMessagingHosts"
            / f"{HOST_NAME}.json"
        ).unlink(missing_ok=True)
    launchctl("bootout", f"gui/{os.getuid()}/{SOURCE_LABEL}", check=False)
    (Path.home() / "Library/LaunchAgents" / f"{SOURCE_LABEL}.plist").unlink(
        missing_ok=True
    )


async def control(config: SourceConfig, command: str, site: str | None) -> int:
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{SOURCE_PORT}", timeout=65, trust_env=False
    ) as http:
        client = SignedClient(http, config.secret)
        failed = False
        for target in (site,) if site else known_session_sites():
            try:
                if command in {"login", "finish"}:
                    await client.post(
                        LOGIN_PATH,
                        LoginRequest(site=target, finish=command == "finish"),
                        LoginResponse,
                    )
                    print(f"{target}\t{command}")
                else:
                    await client.post(
                        STATUS_PATH, StatusRequest(site=target), StatusResponse
                    )
                    print(f"{target}\tsource_ready (platform acceptance not verified)")
            except RpcError as error:
                print(f"{target}\t{error.code}")
                failed = True
        return 2 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Chrome platform session source")
    parser.add_argument(
        "command", choices=("serve", "install", "uninstall", "check", "login", "finish")
    )
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--site", choices=known_session_sites())
    args = parser.parse_args()
    if args.command == "uninstall":
        uninstall()
        return 0
    config = load_config(args.env_file)
    if args.command == "install":
        if sys.platform != "darwin":
            raise SystemExit("LaunchAgent installation requires macOS")
        install(config)
        print(
            "Chrome source installed. Load the extension directory printed below in chrome://extensions."
        )
        print(config.root / "ChromeExtension")
        return 0
    if args.command in {"check", "login", "finish"}:
        if args.command != "check" and args.site is None:
            parser.error("login and finish require --site")
        return asyncio.run(control(config, args.command, args.site))
    source = ChromeSource(secret=config.secret)
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
