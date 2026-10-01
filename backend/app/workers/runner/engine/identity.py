"""Runner-only identity transport and operation-owned Cookie tmpfs lifecycle."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import stat
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from app.services.provider_failures import FailureClass
from app.services.provider_types import ProviderIdentity
from app.workers.runner.engine.layers.base import LayerFailure
from app.workers.runner.netscape_cookie import MAX_COOKIE_BYTES, parse_cookie_payload
from app.workers.runner.provider_registry import provider_profile_for_key
from app.workers.runner.settings import get_runner_settings


@dataclass(frozen=True, slots=True)
class IdentityMaterial:
    cookie_file: Path = field(repr=False)
    digest: str

    def cleanup(self) -> None:
        self.cookie_file.unlink(missing_ok=True)
        self.cookie_file.parent.rmdir()


def _unavailable(cause: str) -> LayerFailure:
    return LayerFailure(
        FailureClass.IDENTITY_UNAVAILABLE, "③", {"kind": "runtime", "cause_code": cause}
    )


def _is_tmpfs(root: Path) -> bool:
    # Linux statfs ABI starts with a long filesystem magic; require TMPFS_MAGIC.
    import ctypes
    import sys

    if sys.platform != "linux":
        return False
    library = ctypes.CDLL(None, use_errno=True)
    library.statfs.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
    library.statfs.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(256)
    if library.statfs(os.fsencode(root), buffer) != 0:
        return False
    return ctypes.c_long.from_buffer(buffer).value == 0x01021994


def _private_root(root: Path) -> Path:
    if (
        not root.is_absolute()
        or root == Path("/")
        or root.name != "framefetch-identity"
    ):
        raise _unavailable("identity_tmpfs_path_invalid")
    # Refuse symlinks in every ancestor, before mkdir or deletion.
    for part in (root, *root.parents):
        if part.is_symlink():
            raise _unavailable("identity_tmpfs_path_invalid")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = root.stat()
    if (
        metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or not _is_tmpfs(root)
    ):
        raise _unavailable("identity_tmpfs_unavailable")
    return root


def initialize_identity_tmpfs(root: Path | None = None) -> None:
    """Call once in Runner lifespan, before accepting requests."""
    private = _private_root(root or get_runner_settings().runner_identity_tmpfs_root)
    for item in private.iterdir():
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item)
        else:
            item.unlink()


async def fetch_identity(
    site: str, task_id: str, deadline: datetime
) -> IdentityMaterial:
    """Design 17 interface: no persistence, retries, redirects or ambient proxies."""
    operation: Path | None = None
    try:
        if deadline.tzinfo is None:
            raise _unavailable("identity_deadline_invalid")
        remaining = (deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0 or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", task_id
        ):
            raise _unavailable("identity_deadline_invalid")
        profile = provider_profile_for_key(site)
        if (
            profile.identity is ProviderIdentity.NONE
            or not profile.cookie_domain_allowlist
        ):
            raise _unavailable("identity_not_declared")
        settings = get_runner_settings()
        if settings.cookie_source_token is None:
            raise _unavailable("identity_not_configured")
        root = _private_root(settings.runner_identity_tmpfs_root)
        token = settings.cookie_source_token.get_secret_value()
        # Inspect and download never share operation directories.
        operation = root / uuid4().hex
        operation.mkdir(mode=0o700)
        endpoint = f"http://host.docker.internal:{settings.cookie_source_port}/cookies"
        async with asyncio.timeout(remaining):
            async with httpx.AsyncClient(
                proxy=settings.runner_egress_proxy,
                trust_env=False,
                follow_redirects=False,
                timeout=min(120, remaining),
            ) as client:
                async with client.stream(
                    "POST",
                    endpoint,
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "site": site,
                        "task_id": task_id,
                        "deadline": deadline.isoformat(),
                    },
                ) as response:
                    payload = bytearray()
                    async for chunk in response.aiter_bytes():
                        payload.extend(chunk)
                        if len(payload) > 2 * MAX_COOKIE_BYTES:
                            raise _unavailable("identity_material_invalid")
        result = json.loads(payload)
        if response.status_code != 200:
            cause = result.get("cause") if isinstance(result, dict) else None
            if cause not in {
                "extension_disconnected",
                "extension_timeout",
                "credential_missing",
                "identity_cookie_rules_unverified",
                "identity_not_declared",
                "identity_deadline_invalid",
            }:
                cause = "cookie_source_rejected"
            raise _unavailable(cause)
        if set(result) != {"cookies", "digest"} or not re.fullmatch(
            r"[a-f0-9]{64}", result["digest"]
        ):
            raise _unavailable("identity_material_invalid")
        cookies = base64.b64decode(result["cookies"], validate=True)
        lines = parse_cookie_payload(cookies, profile.cookie_domain_allowlist)
        if any(
            (line.expires and line.expires <= time.time())
            or not line.line.split(b"\t")[6]
            for line in lines
        ):
            raise _unavailable("identity_material_invalid")
        if datetime.now(UTC) >= deadline:
            raise _unavailable("identity_deadline_invalid")
        cookie_file = operation / "cookies.txt"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(cookie_file, flags, 0o600), "wb") as stream:
            stream.write(cookies)
        return IdentityMaterial(cookie_file, result["digest"])
    except asyncio.CancelledError:
        if operation is not None:
            shutil.rmtree(operation)
        raise
    except Exception as error:
        if operation is not None:
            shutil.rmtree(operation)
        if isinstance(error, LayerFailure):
            raise
        raise _unavailable("cookie_source_unavailable") from None


@asynccontextmanager
async def operation_identity(
    site: str, task_id: str, deadline: datetime
) -> AsyncIterator[IdentityMaterial]:
    """Caller owns the full resolve/download operation; finally deletes its material."""
    material = await fetch_identity(site, task_id, deadline)
    try:
        yield material
    finally:
        material.cleanup()


class IdentityOperation:
    """Declaration policy and one optional injection owned by a Runner operation."""

    def __init__(self, site: str, task_id: str, deadline: datetime):
        self.site = site
        self.task_id = task_id
        self.deadline = deadline
        self.policy = provider_profile_for_key(site).identity
        self.material: IdentityMaterial | None = None
        self._attempted = False

    async def __aenter__(self) -> IdentityOperation:
        if self.policy is ProviderIdentity.REQUIRED:
            self.material = await fetch_identity(self.site, self.task_id, self.deadline)
        return self

    async def after_login_required(self) -> bool:
        """Call only for classified login_required evidence; true means retry once."""
        if self.policy is not ProviderIdentity.OPTIONAL or self._attempted:
            return False
        self._attempted = True
        self.material = await fetch_identity(self.site, self.task_id, self.deadline)
        return True

    async def __aexit__(self, *exception: object) -> None:
        if self.material is not None:
            self.material.cleanup()


COOKIE_TMPFS_ROOT = Path("/tmp/framefetch-identity")


def validate_cookie_file(path: Path) -> None:
    """Accept only an owner-private regular file on Runner's tmpfs mount."""
    import os
    import stat

    from app.workers.runner.errors import RunnerFailure

    try:
        relative = path.relative_to(COOKIE_TMPFS_ROOT)
        if not path.is_absolute() or len(relative.parts) != 2 or ".." in relative.parts:
            raise ValueError("invalid material path")
        for parent in (COOKIE_TMPFS_ROOT, path.parent):
            info = parent.lstat()
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700
            ):
                raise ValueError("non-private material directory")
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise ValueError("non-private material file")
        if path.resolve() != path or not _on_tmpfs(path):
            raise ValueError("material is outside private tmpfs")
    except (OSError, ValueError) as exc:
        raise RunnerFailure("invalid_input", status=422) from exc


def _on_tmpfs(path: Path) -> bool:
    mounts = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        fields, filesystem = line.split(" - ", 1)
        mount = Path(fields.split()[4])
        if path.is_relative_to(mount):
            mounts.append((len(mount.parts), filesystem.split()[0]))
    return bool(mounts) and max(mounts)[1] == "tmpfs"
