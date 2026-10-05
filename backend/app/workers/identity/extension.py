"""Generate the unpacked extension permissions from the current Registry."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path

from app.core.config import CookieSourceSettings
from app.services.provider_types import ProviderIdentity
from app.workers.identity.yuanbao_parse import YUANBAO_ORIGIN
from app.workers.runner.provider_registry import current_provider_registry

EXTENSION_SOURCE = Path(__file__).resolve().parents[4] / "browser-extension"


def extension_home() -> Path:
    # --git-common-dir points to the primary checkout even inside a worktree.
    common = subprocess.run(
        [
            "git",
            "-C",
            str(EXTENSION_SOURCE.parent),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.strip()
    return Path(common).parent / "browser-extension"


def cookie_domains() -> list[str]:
    return sorted(
        {
            domain.lstrip(".").lower()
            for profile in current_provider_registry().profiles
            if profile.identity in {ProviderIdentity.REQUIRED, ProviderIdentity.PREFER}
            and profile.identity_source == "cookies"
            for domain in profile.cookie_domain_allowlist
        }
    )


def request_origins() -> list[str]:
    return sorted(
        {
            YUANBAO_ORIGIN
            for profile in current_provider_registry().profiles
            if profile.key == "wechat_channels"
            and profile.identity in {ProviderIdentity.REQUIRED, ProviderIdentity.PREFER}
            and profile.identity_source == "yuanbao_http"
            and profile.identity_origin == YUANBAO_ORIGIN
        }
    )


def manifest(port: int) -> dict[str, object]:
    result: dict[str, object] = json.loads(
        (EXTENSION_SOURCE / "manifest.template.json").read_text()
    )
    result["host_permissions"] = [
        *(f"*://*.{domain}/*" for domain in cookie_domains()),
        *(f"{origin}/*" for origin in request_origins()),
        f"ws://127.0.0.1:{port}/",
    ]
    return result


def extension_origin() -> str:
    key = json.loads((EXTENSION_SOURCE / "manifest.template.json").read_text())["key"]
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


def require_untracked_outputs(destination: Path) -> None:
    for name in ("config.local.json", "manifest.json"):
        result = subprocess.run(
            ["git", "-C", str(destination), "ls-files", "--error-unmatch", "--", name],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 1:
            raise ValueError("identity_generated_file_tracked")
        ignored = subprocess.run(
            ["git", "-C", str(destination), "check-ignore", "--quiet", "--", name],
            capture_output=True,
            timeout=5,
        )
        if ignored.returncode != 0:
            raise ValueError("identity_generated_file_not_ignored")


def install_extension(settings: CookieSourceSettings) -> Path:
    destination = extension_home()
    if destination.resolve() != EXTENSION_SOURCE.resolve():
        raise ValueError("identity_install_requires_primary_workspace")
    require_untracked_outputs(destination)
    private_directory(destination)
    private_write(
        destination / "manifest.json",
        json.dumps(manifest(settings.cookie_source_port), indent=2) + "\n",
    )
    # Not web-accessible; local pairing data is never shipped or tracked.
    config = {
        "port": settings.cookie_source_port,
        "pairingKey": settings.cookie_source_pairing_key.get_secret_value(),
        "domains": cookie_domains(),
        "yuanbaoParse": YUANBAO_ORIGIN in request_origins(),
    }
    private_write(destination / "config.local.json", json.dumps(config) + "\n")
    require_untracked_outputs(destination)
    return destination
