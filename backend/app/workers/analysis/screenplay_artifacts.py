from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
import stat
import tempfile
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import Protocol
from uuid import UUID

from app.services.analysis_execution.errors import AnalysisArtifactError
from app.services.analysis_execution.models import (
    AnalysisScreenplaySource,
    LocalScreenplayArtifact,
)

_SHA256 = re.compile(r"[0-9a-f]{64}")


class ScreenplayStorage(Protocol):
    async def download(self, object_key: str, target: Path) -> None: ...


class LocalScreenplayArtifactLoader:
    def __init__(
        self,
        storage: ScreenplayStorage,
        *,
        workspace_root: Path,
        bucket: str,
        max_source_bytes: int,
    ) -> None:
        if max_source_bytes <= 0:
            raise ValueError("screenplay source byte limit must be positive")
        self._storage = storage
        self._root = workspace_root.expanduser().absolute()
        self._bucket = bucket
        self._max_source_bytes = max_source_bytes

    async def prepare_root(self) -> None:
        await asyncio.to_thread(self._prepare_root)

    async def materialize(
        self,
        source: AnalysisScreenplaySource,
        *,
        job_id: UUID,
        attempt: int,
    ) -> LocalScreenplayArtifact:
        _validate_source(source, self._bucket, self._max_source_bytes)
        workspace = await asyncio.to_thread(self._create_workspace, job_id, attempt)
        input_directory = workspace / "input"
        input_directory.mkdir(mode=0o700)
        local = LocalScreenplayArtifact(
            workspace=workspace,
            screenplay=input_directory / "screenplay.md",
        )
        try:
            await self._storage.download(source.object_key, local.screenplay)
            await asyncio.to_thread(
                _verify_screenplay, local, source, self._max_source_bytes
            )
            local.screenplay.chmod(0o400)
            return local
        except asyncio.CancelledError:
            await asyncio.shield(self.cleanup(local))
            raise
        except AnalysisArtifactError:
            await self.cleanup(local)
            raise
        except Exception as exc:
            await self.cleanup(local)
            raise AnalysisArtifactError("artifact_storage_unavailable") from exc

    async def cleanup(self, local: LocalScreenplayArtifact) -> None:
        await asyncio.to_thread(self._cleanup, local.workspace)

    def _prepare_root(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self._root.is_symlink() or not self._root.is_dir():
            raise AnalysisArtifactError("invalid_analysis_workspace")
        self._root.chmod(0o700)

    def _create_workspace(self, job_id: UUID, attempt: int) -> Path:
        self._prepare_root()
        if attempt < 1:
            raise AnalysisArtifactError("invalid_analysis_workspace")
        path = Path(
            tempfile.mkdtemp(prefix=f"analysis-{job_id.hex}-{attempt}-", dir=self._root)
        )
        path.chmod(0o700)
        resolved = path.resolve(strict=True)
        if resolved.parent != self._root.resolve(strict=True):
            raise AnalysisArtifactError("invalid_analysis_workspace")
        return resolved

    def _cleanup(self, workspace: Path) -> None:
        with suppress(OSError):
            if workspace.parent.resolve() != self._root.resolve(strict=True):
                return
            if workspace.is_symlink() or not workspace.is_dir():
                workspace.unlink(missing_ok=True)
                return
            for path in workspace.rglob("*"):
                with suppress(OSError):
                    path.chmod(0o700)
            shutil.rmtree(workspace)


def _validate_source(
    source: AnalysisScreenplaySource, bucket: str, maximum: int
) -> None:
    parts = PurePosixPath(source.object_key).parts
    valid_key = (
        len(parts) == 4
        and parts[0] == "documents"
        and parts[1] == str(source.document_id)
        and parts[2].isdigit()
        and int(parts[2]) > 0
        and parts[3] in {"screenplay.md", "document.md"}
    )
    if (
        source.bucket != bucket
        or not valid_key
        or _SHA256.fullmatch(source.sha256) is None
        or source.size_bytes > maximum
        or source.character_count > maximum
    ):
        raise AnalysisArtifactError("input_artifact_unavailable")


def _verify_screenplay(
    local: LocalScreenplayArtifact,
    source: AnalysisScreenplaySource,
    maximum: int,
) -> None:
    try:
        if local.screenplay.is_symlink():
            raise OSError
        info = local.screenplay.stat()
        resolved = local.screenplay.resolve(strict=True)
        if (
            not stat.S_ISREG(info.st_mode)
            or not resolved.is_relative_to(local.workspace / "input")
            or info.st_size != source.size_bytes
            or info.st_size > maximum
        ):
            raise OSError
        content = resolved.read_bytes()
        if hashlib.sha256(content).hexdigest() != source.sha256:
            raise OSError
        text = content.decode("utf-8", errors="strict")
        if (
            len(text) != source.character_count
            or "\r" in text
            or "\x00" in text
            or any(not text[scene.start : scene.end] for scene in source.scenes)
        ):
            raise OSError
    except (OSError, UnicodeDecodeError) as exc:
        raise AnalysisArtifactError("artifact_integrity_failed") from exc
