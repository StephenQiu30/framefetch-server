"""Generate the unpacked extension permissions from the current Registry."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

from app.core.config import CookieSourceSettings
from app.services.provider_types import ProviderIdentity
from app.workers.runner.provider_registry import current_provider_registry

EXTENSION_SOURCE = Path(__file__).resolve().parents[4] / "browser-extension"


def extension_home() -> Path:
    return Path.home() / "Library/Application Support/FrameFetch/extension"


def cookie_domains() -> list[str]:
    return sorted(
        {
            domain.lstrip(".").lower()
            for profile in current_provider_registry().profiles
            if profile.identity is not ProviderIdentity.NONE
            for domain in profile.cookie_domain_allowlist
        }
    )


def manifest(port: int) -> dict[str, object]:
    result: dict[str, object] = json.loads(
        (EXTENSION_SOURCE / "manifest.json").read_text()
    )
    result["host_permissions"] = [
        *(f"*://*.{domain}/*" for domain in cookie_domains()),
        f"ws://127.0.0.1:{port}/",
    ]
    return result


def extension_origin() -> str:
    key = json.loads((EXTENSION_SOURCE / "manifest.json").read_text())["key"]
    digest = hashlib.sha256(base64.b64decode(key, validate=True)).hexdigest()[:32]
    extension_id = "".join(chr(ord("a") + int(char, 16)) for char in digest)
    return f"chrome-extension://{extension_id}"


def private_directory(path: Path) -> None:
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise ValueError("identity_directory_symlink")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.stat().st_uid != os.getuid():
        raise ValueError("identity_directory_owner")
    path.chmod(0o700)


def private_write(path: Path, content: str) -> None:
    if path.exists() and (path.is_symlink() or path.stat().st_uid != os.getuid()):
        raise ValueError("identity_file_owner")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags, 0o600), "w") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(content)


def install_extension(settings: CookieSourceSettings) -> Path:
    destination = extension_home()
    private_directory(destination.parent)
    private_directory(destination)
    for name in ("background.js", "protocol.js"):
        private_write(destination / name, (EXTENSION_SOURCE / name).read_text())
    private_write(
        destination / "manifest.json",
        json.dumps(manifest(settings.cookie_source_port), indent=2) + "\n",
    )
    # Not web-accessible; install-time only, never part of the source/distribution.
    config = {
        "port": settings.cookie_source_port,
        "pairingKey": settings.cookie_source_pairing_key.get_secret_value(),
        "domains": cookie_domains(),
    }
    private_write(
        destination / "config.js",
        "globalThis.FRAMEFETCH_CONFIG = " + json.dumps(config) + ";\n",
    )
    return destination
