"""Enumerate the installed engine in a bounded, credential-free child process."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

from app.schemas.engine_catalog import EngineCandidateResponse, EngineCatalogResponse
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.process import ProcessSupervisor
from app.workers.runner.readiness import _package_record
from app.workers.runner.settings import RunnerSettings
from app.workers.runner.version import (
    YOUTUBE_POT_PROVIDER_VERSION,
    YTDLP_ENGINE_VERSION,
)
from packaging.version import Version
from pydantic import ValidationError

_ROOT = Path(__file__).resolve().parent
_SOURCE = re.compile(
    r"https://github\.com/yt-dlp/yt-dlp/archive/([0-9a-f]{40})\.tar\.gz"
)


class RunnerEngineCatalog:
    def __init__(self, settings: RunnerSettings) -> None:
        self._settings = settings
        self._lock = asyncio.Lock()
        self._snapshot: EngineCatalogResponse | None = None

    async def get(self) -> EngineCatalogResponse:
        # A replaced image creates a new process and therefore a new snapshot.
        # Failure never serves a fabricated or previous-image catalog.
        try:
            async with asyncio.timeout(12), self._lock:
                if self._snapshot is not None:
                    return self._snapshot
                executable = shutil.which(self._settings.runner_ytdlp_bin)
                installed = Path(sys.executable).parent / "yt-dlp"
                if (
                    executable is None
                    or Path(executable).resolve() != installed.resolve()
                ):
                    raise RunnerFailure("engine_catalog_unavailable", status=503)
                result = await ProcessSupervisor(
                    stdout_limit_bytes=2 * 1024 * 1024,
                    stderr_limit_bytes=4096,
                ).run(
                    (
                        sys.executable,
                        "-m",
                        "app.workers.runner.engine_catalog",
                        self._settings.runner_ytdlp_commit,
                        self._settings.runner_youtube_pot_provider_version,
                    ),
                    cwd=_ROOT.parents[2],
                    timeout_seconds=8,
                    # Enumeration needs neither settings nor provider credentials.
                    env={
                        key: value
                        for key, value in os.environ.items()
                        if key in {"PATH", "SYSTEMROOT", "YTDLP_NO_PLUGINS"}
                    },
                )
                if result.returncode != 0 or result.stdout_truncated:
                    raise RunnerFailure("engine_catalog_unavailable", status=503)
                self._snapshot = EngineCatalogResponse.model_validate_json(
                    result.stdout
                )
                return self._snapshot
        except (OSError, TimeoutError, ValidationError) as exc:
            raise RunnerFailure("engine_catalog_unavailable", status=503) from exc


def collect_catalog(
    expected_commit: str, configured_pot_version: str
) -> EngineCatalogResponse:
    """Run only in the child: yt-dlp plugin registration mutates global state."""
    from yt_dlp.extractor import gen_extractor_classes  # type: ignore[import-untyped]
    from yt_dlp.globals import plugin_dirs  # type: ignore[import-untyped]
    from yt_dlp.plugins import load_all_plugins  # type: ignore[import-untyped]

    # Same explicit plugin root as YtDlpCommandBuilder, without ambient config.
    # yt-dlp's --list-extractors exits before this plugin-loading step.
    plugin_dirs.value = [str(_ROOT)]
    load_all_plugins()
    candidates = tuple(
        sorted(
            (
                EngineCandidateResponse(
                    key=extractor.ie_key(),
                    name=extractor.IE_NAME,
                    upstream_working=extractor.working(),
                )
                for extractor in gen_extractor_classes()
            ),
            key=lambda item: (item.name.casefold(), item.key),
        )
    )
    package = _package_record("yt-dlp")
    if package is None:
        raise RuntimeError("engine package is unavailable")
    source = _SOURCE.fullmatch(package[1] or "")
    commit = source[1] if source is not None else None
    pot_package = _package_record("bgutil-ytdlp-pot-provider")
    digest = hashlib.sha256()
    for path in sorted((_ROOT / "plugins").rglob("*.py")):
        digest.update(path.relative_to(_ROOT).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    snapshot = EngineCatalogResponse(
        engine_version=package[0],
        engine_commit=commit,
        expected_engine_commit=expected_commit,
        pin_matches=(
            commit == expected_commit
            and Version(package[0]) == Version(YTDLP_ENGINE_VERSION)
            and pot_package is not None
            and pot_package[0] == YOUTUBE_POT_PROVIDER_VERSION
            and configured_pot_version == f"bgutil-http-{YOUTUBE_POT_PROVIDER_VERSION}"
        ),
        bundled_plugins_sha256=digest.hexdigest(),
        pot_provider_version=None if pot_package is None else pot_package[0],
        manifest_id="0" * 64,
        candidates=candidates,
    )
    document = snapshot.model_dump(mode="json", exclude={"manifest_id"})
    identity = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return snapshot.model_copy(update={"manifest_id": identity})


if __name__ == "__main__":
    print(collect_catalog(sys.argv[1], sys.argv[2]).model_dump_json())
