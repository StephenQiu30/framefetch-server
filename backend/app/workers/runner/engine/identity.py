"""Runner-only identity material. P0 never reads host account state."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.services.provider_failures import FailureClass
from app.workers.runner.engine.layers.base import LayerFailure


@dataclass(frozen=True, slots=True)
class IdentityMaterial:
    cookie_file: Path = field(repr=False)
    digest: str


async def fetch_identity(
    site: str, task_id: str, deadline: datetime
) -> IdentityMaterial:
    raise LayerFailure(
        FailureClass.IDENTITY_UNAVAILABLE,
        "③",
        {"kind": "runtime", "cause_code": "identity_not_implemented"},
    )


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
