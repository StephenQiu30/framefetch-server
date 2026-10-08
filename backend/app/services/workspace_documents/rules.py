"""Rules for the Markdown documents maintained under workspace/content."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from app.services.workspace_documents.errors import (
    WorkspaceDocumentError,
    WorkspaceDocumentErrorCode,
)

MAX_DOCUMENT_BYTES = 512 * 1024
_SEGMENT = re.compile(r"^[^/\\\x00-\x1f\x7f.][^/\\\x00-\x1f\x7f]{0,159}$")
_TITLE = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class WorkspaceDocumentSummary:
    path: str
    title: str
    section: str


@dataclass(frozen=True, slots=True)
class WorkspaceDocument:
    path: str
    title: str
    content: str
    sha256: str
    updated_at: datetime


def normalize_document_path(raw: str) -> str:
    """Accept only relative Markdown paths without hidden or parent segments."""
    segments = raw.split("/")
    if (
        not raw
        or len(raw) > 512
        or not all(_SEGMENT.fullmatch(segment) for segment in segments)
        or PurePosixPath(raw).suffix != ".md"
    ):
        raise WorkspaceDocumentError(WorkspaceDocumentErrorCode.INVALID_PATH)
    return "/".join(segments)


def document_title(content: str, path: str) -> str:
    match = _TITLE.search(content)
    return match.group(1).strip() if match else PurePosixPath(path).stem


def document_section(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else ""


def content_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def prepare_content(content: str) -> str:
    """Store LF line endings with exactly one trailing newline."""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"
    if len(normalized.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise WorkspaceDocumentError(WorkspaceDocumentErrorCode.TOO_LARGE)
    return normalized


def ensure_unchanged(base_sha256: str, current: str) -> None:
    if content_digest(current) != base_sha256:
        raise WorkspaceDocumentError(WorkspaceDocumentErrorCode.CONFLICT)
