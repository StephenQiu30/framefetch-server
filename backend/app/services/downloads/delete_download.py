from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.services.downloads.download_models import JobSnapshot
from app.services.downloads.errors import (
    ApplicationError,
    ApplicationErrorCode,
    PersistenceConflict,
    PersistenceNotFound,
)
from app.services.downloads.ports import DownloadDeletionStorage, DownloadRepository
from app.services.downloads.rules.enums import DownloadStatus
from app.services.downloads.validation import validate_now, validate_owner_hash
from app.services.imports.errors import (
    ImportObjectStorageError,
    MultipartUploadNotFound,
)


class DownloadCanceller(Protocol):
    async def __call__(self, job_id: UUID, owner_hash: str) -> object: ...


class DeleteDownload:
    def __init__(
        self,
        repository: DownloadRepository,
        storage: DownloadDeletionStorage,
        cancel: DownloadCanceller,
        *,
        now: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._cancel = cancel
        self._now = now

    async def __call__(self, job_id: UUID, owner_hash: str) -> None:
        owner_hash = validate_owner_hash(owner_hash)
        job = await self._owned_job(job_id, owner_hash)
        if job.status in {
            DownloadStatus.QUEUED.value,
            DownloadStatus.RUNNING.value,
            DownloadStatus.RETRY_WAIT.value,
        }:
            await self._cancel(job_id, owner_hash)
        now = validate_now(self._now())
        try:
            plan = await self._repository.prepare_download_deletion(
                job_id, owner_hash, now=now
            )
        except PersistenceNotFound as exc:
            raise ApplicationError(ApplicationErrorCode.NOT_FOUND) from exc
        except PersistenceConflict as exc:
            raise ApplicationError(ApplicationErrorCode.INVALID_STATE) from exc
        if plan.job_id != job_id or plan.owner_hash != owner_hash:
            raise ApplicationError(ApplicationErrorCode.INTERNAL_ERROR)
        for cleanup in plan.cleanup:
            _validate_deletion_key(cleanup.object_key, job_id, plan.attempt)
            try:
                if cleanup.upload_id is not None:
                    with suppress(MultipartUploadNotFound):
                        await self._storage.abort_multipart_upload(
                            cleanup.object_key, cleanup.upload_id
                        )
                await self._storage.delete(cleanup.object_key)
            except ImportObjectStorageError as exc:
                raise ApplicationError(
                    ApplicationErrorCode.STORAGE_UNAVAILABLE
                ) from exc
        try:
            await self._repository.finish_download_deletion(job_id, owner_hash)
        except PersistenceNotFound as exc:
            raise ApplicationError(ApplicationErrorCode.NOT_FOUND) from exc

    async def _owned_job(self, job_id: UUID, owner_hash: str) -> JobSnapshot:
        try:
            job = await self._repository.get_job(job_id)
        except PersistenceNotFound as exc:
            raise ApplicationError(ApplicationErrorCode.NOT_FOUND) from exc
        if job is None or job.owner_hash != owner_hash:
            raise ApplicationError(ApplicationErrorCode.NOT_FOUND)
        return job


def _validate_deletion_key(object_key: str, job_id: UUID, attempt: int) -> None:
    escaped = re.escape(str(job_id))
    if re.fullmatch(
        rf"watermarks/{escaped}/[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}/[1-9][0-9]*/video\.mp4",
        object_key,
    ):
        return
    attempt_patterns = (
        rf"downloads/{escaped}/([1-9][0-9]*)/video\.[a-z0-9]{{1,16}}",
        rf"quarantine/video/{escaped}/([1-9][0-9]*)/source",
    )
    for pattern in attempt_patterns:
        match = re.fullmatch(pattern, object_key)
        if match is not None and int(match.group(1)) <= attempt:
            return
    if re.fullmatch(
        rf"thumbnails/{escaped}/[0-9a-f]{{64}}\.(?:avif|jpg|png|webp)",
        object_key,
    ):
        return
    raise ApplicationError(ApplicationErrorCode.INTERNAL_ERROR)
