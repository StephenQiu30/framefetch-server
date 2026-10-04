"""Owner-scoped screenplay document queries."""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from uuid import UUID

from app.services.documents.models import DocumentPage, DocumentView
from app.services.documents.ports import (
    DocumentDeletionRepository,
    DocumentPreviewStorage,
    DocumentReader,
)
from app.services.documents.preview import read_document_preview
from app.services.documents.views import document_page, document_view
from app.services.imports.errors import (
    ImportApplicationError,
    ImportApplicationErrorCode,
    ImportObjectStorageError,
    ImportPersistenceConflict,
    ImportPersistenceError,
    ImportPersistenceNotFound,
    MultipartUploadNotFound,
)
from app.services.imports.ports import QuarantineObjectStorage

_OWNER_HASH = re.compile(r"[0-9a-f]{64}")


class GetDocument:
    def __init__(
        self,
        reader: DocumentReader,
        storage: DocumentPreviewStorage,
        *,
        max_preview_bytes: int,
        max_preview_characters: int,
    ) -> None:
        if not 1 <= max_preview_bytes <= 1 * 1024**2:
            raise ValueError("document preview byte limit is invalid")
        if not 1 <= max_preview_characters <= 1_000_000:
            raise ValueError("document preview character limit is invalid")
        self._reader = reader
        self._storage = storage
        self._max_preview_bytes = max_preview_bytes
        self._max_preview_characters = max_preview_characters

    async def __call__(self, document_id: UUID, owner_hash: str) -> DocumentView:
        owner_hash = _owner_hash(owner_hash)
        snapshot = await self._reader.get_document(document_id, owner_hash)
        if snapshot is None or snapshot.owner_hash != owner_hash:
            raise ImportApplicationError(ImportApplicationErrorCode.NOT_FOUND)
        preview, truncated = await read_document_preview(
            snapshot,
            self._storage,
            max_bytes=self._max_preview_bytes,
            max_characters=self._max_preview_characters,
        )
        return document_view(snapshot, preview=preview, preview_truncated=truncated)


class ListDocuments:
    def __init__(self, reader: DocumentReader) -> None:
        self._reader = reader

    async def __call__(
        self, owner_hash: str, *, page: int = 1, page_size: int = 20
    ) -> DocumentPage:
        owner_hash = _owner_hash(owner_hash)
        if not 1 <= page <= 10_000 or not 1 <= page_size <= 50:
            raise ImportApplicationError(ImportApplicationErrorCode.INVALID_REQUEST)
        snapshot = await self._reader.list_documents(
            owner_hash, page=page, page_size=page_size
        )
        return document_page(snapshot, owner_hash)


class DeleteDocument:
    def __init__(
        self,
        repository: DocumentDeletionRepository,
        storage: QuarantineObjectStorage,
        *,
        now: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._now = now

    async def __call__(self, document_id: UUID, owner_hash: str) -> None:
        owner_hash = _owner_hash(owner_hash)
        now = self._now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ImportApplicationError(ImportApplicationErrorCode.INTERNAL_ERROR)
        try:
            plan = await self._repository.prepare_document_deletion(
                document_id, owner_hash, now=now
            )
        except ImportPersistenceError as error:
            raise _persistence_error(error) from error
        if plan.document_id != document_id or plan.owner_hash != owner_hash:
            raise ImportApplicationError(ImportApplicationErrorCode.INTERNAL_ERROR)
        for cleanup in plan.cleanup:
            _validate_deletion_key(cleanup.object_key, document_id, plan.attempt)
        keys: list[str] = []
        for cleanup in plan.cleanup:
            try:
                if cleanup.upload_id is not None:
                    with suppress(MultipartUploadNotFound):
                        await self._storage.abort_multipart_upload(
                            cleanup.object_key, cleanup.upload_id
                        )
                await self._storage.delete(cleanup.object_key)
            except ImportObjectStorageError as error:
                raise ImportApplicationError(
                    ImportApplicationErrorCode.STORAGE_UNAVAILABLE
                ) from error
            keys.append(cleanup.object_key)
        try:
            await self._repository.finish_document_deletion(
                document_id, owner_hash, object_keys=tuple(keys), now=now
            )
        except ImportPersistenceError as error:
            raise _persistence_error(error) from error


def _owner_hash(value: str) -> str:
    if _OWNER_HASH.fullmatch(value) is None:
        raise ImportApplicationError(ImportApplicationErrorCode.INVALID_REQUEST)
    return value


def _validate_deletion_key(object_key: str, document_id: UUID, attempt: int) -> None:
    for prefix, final_names in (
        (f"quarantine/screenplay/{document_id}/", {"source"}),
        (f"documents/{document_id}/", {"original", "document.md", "screenplay.md"}),
    ):
        if object_key.startswith(prefix):
            parts = object_key.removeprefix(prefix).split("/")
            if (
                len(parts) == 2
                and parts[0].isdigit()
                and 1 <= int(parts[0]) <= attempt
                and parts[1] in final_names
            ):
                return
    raise ImportApplicationError(ImportApplicationErrorCode.INTERNAL_ERROR)


def _persistence_error(error: ImportPersistenceError) -> ImportApplicationError:
    if isinstance(error, ImportPersistenceNotFound):
        return ImportApplicationError(ImportApplicationErrorCode.NOT_FOUND)
    if isinstance(error, ImportPersistenceConflict):
        return ImportApplicationError(ImportApplicationErrorCode.INVALID_STATE)
    return ImportApplicationError(ImportApplicationErrorCode.INTERNAL_ERROR)
