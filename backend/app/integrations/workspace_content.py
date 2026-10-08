"""Filesystem access to the Markdown documents under workspace/content."""

from __future__ import annotations

import asyncio
import fcntl
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from app.services.workspace_documents.errors import (
    WorkspaceDocumentError,
    WorkspaceDocumentErrorCode,
)
from app.services.workspace_documents.rules import (
    MAX_DOCUMENT_BYTES,
    WorkspaceDocument,
    WorkspaceDocumentSummary,
    content_digest,
    document_section,
    document_title,
    ensure_unchanged,
    normalize_document_path,
    prepare_content,
)

_LOCK_NAME = ".workspace-write.lock"


class WorkspaceContentStore:
    """Reads and atomically rewrites existing documents; it never creates or deletes."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def summaries(self) -> list[WorkspaceDocumentSummary]:
        return await asyncio.to_thread(self._list)

    async def read(self, raw_path: str) -> WorkspaceDocument:
        path = normalize_document_path(raw_path)
        return await asyncio.to_thread(self._read, path)

    async def write(
        self, raw_path: str, content: str, base_sha256: str
    ) -> WorkspaceDocument:
        path = normalize_document_path(raw_path)
        prepared = prepare_content(content)
        return await asyncio.to_thread(self._write, path, prepared, base_sha256)

    def _list(self) -> list[WorkspaceDocumentSummary]:
        summaries = []
        for file in sorted(self._root.rglob("*.md")):
            relative = file.relative_to(self._root).as_posix()
            if any(part.startswith(".") for part in relative.split("/")):
                continue
            if file.is_symlink() or not file.is_file():
                continue
            content = self._decode(file)
            summaries.append(
                WorkspaceDocumentSummary(
                    path=relative,
                    title=document_title(content, relative),
                    section=document_section(relative),
                )
            )
        return summaries

    def _read(self, path: str) -> WorkspaceDocument:
        file = self._file(path)
        return self._document(path, file, self._decode(file))

    def _write(self, path: str, content: str, base_sha256: str) -> WorkspaceDocument:
        # Lock a stable file: the document itself is replaced, so its inode changes.
        with (self._root / _LOCK_NAME).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            file = self._file(path)
            ensure_unchanged(base_sha256, self._decode(file))
            mode = file.stat().st_mode & 0o777
            descriptor, temporary = tempfile.mkstemp(
                dir=file.parent, prefix=".", suffix=".tmp"
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as out:
                    out.write(content)
                    out.flush()
                    os.fsync(out.fileno())
                os.chmod(temporary, mode)
                os.replace(temporary, file)
            except BaseException:
                Path(temporary).unlink(missing_ok=True)
                raise
        return self._document(path, file, content)

    def _file(self, path: str) -> Path:
        file = self._root / path
        if file.is_symlink() or not file.is_file():
            raise WorkspaceDocumentError(WorkspaceDocumentErrorCode.NOT_FOUND)
        if not file.resolve().is_relative_to(self._root):
            raise WorkspaceDocumentError(WorkspaceDocumentErrorCode.NOT_FOUND)
        return file

    @staticmethod
    def _decode(file: Path) -> str:
        data = file.read_bytes()
        if len(data) > MAX_DOCUMENT_BYTES:
            raise WorkspaceDocumentError(WorkspaceDocumentErrorCode.TOO_LARGE)
        return data.decode("utf-8")

    @staticmethod
    def _document(path: str, file: Path, content: str) -> WorkspaceDocument:
        return WorkspaceDocument(
            path=path,
            title=document_title(content, path),
            content=content,
            sha256=content_digest(content),
            updated_at=datetime.fromtimestamp(file.stat().st_mtime, tz=UTC),
        )
