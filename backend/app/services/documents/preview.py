from __future__ import annotations

import hashlib
from typing import Never

from app.services.documents.models import DocumentSnapshot
from app.services.documents.ports import DocumentPreviewStorage
from app.services.imports.errors import (
    ImportApplicationError,
    ImportApplicationErrorCode,
    ImportObjectStorageError,
)
from app.services.imports.rules.enums import ImportStatus


async def read_document_preview(
    snapshot: DocumentSnapshot,
    storage: DocumentPreviewStorage,
    *,
    max_bytes: int,
    max_characters: int,
) -> tuple[str | None, bool]:
    if snapshot.status != ImportStatus.READY.value:
        return None, False
    artifact = snapshot.normalized_artifact
    prefix = f"documents/{snapshot.id}/{snapshot.attempt}"
    expected_keys = {f"{prefix}/document.md", f"{prefix}/screenplay.md"}
    if (
        artifact is None
        or artifact.bucket != storage.bucket
        or artifact.object_key not in expected_keys
        or artifact.size_bytes <= 0
        or artifact.sha256 != snapshot.text_sha256
    ):
        _internal_error()
    length = min(artifact.size_bytes, max_bytes)
    try:
        payload = await storage.read_range(artifact.object_key, length=length)
    except ImportObjectStorageError as error:
        raise ImportApplicationError(
            ImportApplicationErrorCode.STORAGE_UNAVAILABLE
        ) from error
    if len(payload) != length:
        _internal_error()
    truncated = artifact.size_bytes > length
    if not truncated and hashlib.sha256(payload).hexdigest() != artifact.sha256:
        _internal_error()
    preview = _decode_preview(payload, truncated=truncated)
    if len(preview) > max_characters:
        preview = preview[:max_characters]
        truncated = True
    return preview, truncated


def _decode_preview(payload: bytes, *, truncated: bool) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        if (
            truncated
            and error.end == len(payload)
            and error.reason == "unexpected end of data"
        ):
            return payload[: error.start].decode("utf-8")
        raise ImportApplicationError(
            ImportApplicationErrorCode.INTERNAL_ERROR
        ) from error


def _internal_error() -> Never:
    raise ImportApplicationError(ImportApplicationErrorCode.INTERNAL_ERROR)
