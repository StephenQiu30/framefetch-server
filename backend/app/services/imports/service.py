from __future__ import annotations

import asyncio
import re
from contextlib import suppress
from datetime import datetime
from pathlib import PurePosixPath
from typing import Never
from uuid import UUID

from app.services.imports.errors import (
    ImportApplicationError,
    ImportApplicationErrorCode,
    ImportObjectStorageError,
    ImportPersistenceConflict,
    ImportPersistenceError,
    ImportPersistenceIdempotencyConflict,
    ImportPersistenceNotFound,
    MultipartUploadNotFound,
    MultipartUploadRejected,
)
from app.services.imports.models import (
    CompletedUploadPart,
    ImportAttemptSnapshot,
    ImportCleanupRef,
    ImportResourceCreate,
    ImportResourceSnapshot,
    ImportView,
    UploadLimits,
    UploadPartTarget,
    UploadSessionView,
)
from app.services.imports.ports import (
    Clock,
    IdFactory,
    ImportRepository,
    ObjectHead,
    QuarantineObjectStorage,
    RequestFingerprinter,
)
from app.services.imports.rules.enums import (
    ContentKind,
    DeclaredOrigin,
    ImportErrorCode,
    ImportSourceFormat,
    ImportStatus,
)
from app.services.imports.rules.keys import quarantine_object_key
from app.services.quotas import DEFAULT_USER_QUOTA, UserQuota

_OWNER_HASH = re.compile(r"[0-9a-f]{64}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_RIGHTS_VERSION = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_FORMAT_SUFFIXES = {
    ImportSourceFormat.MP4: {".mp4"},
    ImportSourceFormat.DOCX: {".docx"},
    ImportSourceFormat.PDF: {".pdf"},
    ImportSourceFormat.TXT: {".txt"},
    ImportSourceFormat.MARKDOWN: {".md", ".markdown"},
    ImportSourceFormat.FOUNTAIN: {".fountain"},
}


class CreateImportResource:
    def __init__(
        self,
        *,
        repository: ImportRepository,
        fingerprinter: RequestFingerprinter,
        now: Clock,
        new_id: IdFactory,
        media_enabled: bool,
        document_enabled: bool,
        media_max_bytes: int,
        document_max_bytes: int,
        rights_statement_version: str,
    ) -> None:
        if media_max_bytes <= 0 or document_max_bytes <= 0:
            raise ValueError("import byte limits must be positive")
        if _RIGHTS_VERSION.fullmatch(rights_statement_version) is None:
            raise ValueError("invalid rights statement version")
        self._repository = repository
        self._fingerprinter = fingerprinter
        self._now = now
        self._new_id = new_id
        self._enabled = {
            ContentKind.VIDEO: media_enabled,
            ContentKind.SCREENPLAY: document_enabled,
        }
        self._max_bytes = {
            ContentKind.VIDEO: media_max_bytes,
            ContentKind.SCREENPLAY: document_max_bytes,
        }
        self._rights_statement_version = rights_statement_version

    async def __call__(
        self,
        *,
        owner_hash: str,
        idempotency_key: str,
        content_kind: ContentKind,
        source_format: ImportSourceFormat,
        file_name: str,
        declared_size_bytes: int,
        declared_sha256: str,
        rights_accepted: bool,
        declared_origin: DeclaredOrigin = DeclaredOrigin.USER_FILE,
        remove_watermark: bool = False,
        quota: UserQuota = DEFAULT_USER_QUOTA,
    ) -> ImportView:
        owner_hash = _validate_owner_hash(owner_hash)
        idempotency_key = _validate_idempotency_key(idempotency_key)
        if not self._enabled[content_kind]:
            raise ImportApplicationError(ImportApplicationErrorCode.DISABLED)
        if source_format.content_kind != content_kind:
            _invalid_request()
        if (
            content_kind is not ContentKind.VIDEO
            and declared_origin is not DeclaredOrigin.USER_FILE
        ):
            _invalid_request()
        if rights_accepted is not True:
            _invalid_request()
        if (
            isinstance(declared_size_bytes, bool)
            or not 0 < declared_size_bytes <= self._max_bytes[content_kind]
        ):
            _invalid_request()
        if _SHA256.fullmatch(declared_sha256) is None:
            _invalid_request()
        display_name = _display_name(file_name, source_format)
        now = _validate_now(self._now())
        command = ImportResourceCreate(
            id=self._new_id(),
            owner_hash=owner_hash,
            idempotency_key=idempotency_key,
            request_fingerprint=self._fingerprinter.fingerprint(
                "content-import",
                content_kind.value,
                source_format.value,
                str(declared_size_bytes),
                declared_sha256,
                self._rights_statement_version,
                declared_origin.value,
                str(remove_watermark),
            ),
            content_kind=content_kind,
            source_format=source_format,
            display_name=display_name,
            content_type=source_format.content_type,
            declared_size_bytes=declared_size_bytes,
            declared_sha256=declared_sha256,
            rights_statement_version=self._rights_statement_version,
            declared_origin=declared_origin,
            remove_watermark=remove_watermark,
            quota=quota,
        )
        try:
            result = await self._repository.create_resource(command, now=now)
        except ImportPersistenceError as error:
            raise _map_persistence_error(error) from error
        _validate_saved_resource(command, result.resource)
        return _view(result.resource)


class CreateUploadSession:
    def __init__(
        self,
        repository: ImportRepository,
        storage: QuarantineObjectStorage,
        *,
        now: Clock,
        limits: UploadLimits,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._now = now
        self._limits = limits

    async def __call__(
        self,
        resource_id: UUID,
        owner_hash: str,
        content_kind: ContentKind,
        *,
        use_local_browser_endpoint: bool = False,
    ) -> UploadSessionView:
        owner_hash = _validate_owner_hash(owner_hash)
        now = _validate_now(self._now())
        resource = await _get_resource(
            self._repository, resource_id, owner_hash, content_kind
        )
        if _status(resource) is not ImportStatus.UPLOADING:
            raise ImportApplicationError(ImportApplicationErrorCode.INVALID_STATE)
        try:
            part_count = self._limits.part_count(resource.declared_size_bytes)
        except ValueError as error:
            raise ImportApplicationError(
                ImportApplicationErrorCode.INVALID_REQUEST
            ) from error
        expires_at = now + self._limits.session_ttl
        try:
            begun = await self._repository.begin_upload_attempt(
                resource_id,
                owner_hash,
                content_kind,
                part_size_bytes=self._limits.part_size_bytes,
                part_count=part_count,
                expires_at=expires_at,
                now=now,
            )
        except ImportPersistenceError as error:
            raise _map_persistence_error(error) from error
        for stale in begun.superseded:
            _validate_cleanup_ref(stale, resource.id, content_kind)
            await _cleanup(self._storage, stale)
        attempt = begun.attempt
        _validate_reserved_attempt(
            attempt,
            resource,
            content_kind,
            self._limits,
            part_count,
            now,
            expires_at,
        )
        upload_id: str | None = None
        try:
            upload_id = await self._storage.create_multipart_upload(
                attempt.object_key,
                content_type=attempt.content_type,
                declared_sha256=resource.declared_sha256,
            )
            active = await self._repository.activate_upload_attempt(
                resource_id,
                owner_hash,
                content_kind,
                attempt.attempt,
                upload_id=upload_id,
                now=now,
            )
            _validate_active_attempt(active, attempt, upload_id)
            ttl_seconds = int((active.expires_at - now).total_seconds())
            if ttl_seconds <= 0:
                raise ImportObjectStorageError("upload session expired before signing")
            urls = await asyncio.gather(
                *(
                    self._storage.presign_upload_part(
                        active.object_key,
                        upload_id,
                        part_number,
                        ttl_seconds=ttl_seconds,
                        size_bytes=min(
                            active.part_size_bytes,
                            resource.declared_size_bytes
                            - (part_number - 1) * active.part_size_bytes,
                        ),
                        use_local_browser_endpoint=use_local_browser_endpoint,
                    )
                    for part_number in range(1, active.part_count + 1)
                )
            )
        except ImportPersistenceError as error:
            if upload_id is not None:
                await _cleanup(
                    self._storage,
                    ImportCleanupRef(attempt.object_key, upload_id),
                )
            raise _map_persistence_error(error) from error
        except ImportObjectStorageError as error:
            with suppress(ImportApplicationError):
                await _record_failure(
                    self._repository,
                    resource_id,
                    owner_hash,
                    content_kind,
                    attempt.attempt,
                    ImportErrorCode.STORAGE_UNAVAILABLE,
                    now,
                )
            if upload_id is not None:
                await _cleanup(
                    self._storage,
                    ImportCleanupRef(attempt.object_key, upload_id),
                )
            raise ImportApplicationError(
                ImportApplicationErrorCode.STORAGE_UNAVAILABLE
            ) from error
        return UploadSessionView(
            resource_id=resource_id,
            attempt=active.attempt,
            part_size_bytes=active.part_size_bytes,
            part_count=active.part_count,
            max_concurrency=self._limits.max_concurrency,
            expires_at=active.expires_at,
            parts=tuple(
                UploadPartTarget(part_number=number, url=url)
                for number, url in enumerate(urls, start=1)
            ),
        )


class CompleteImportUpload:
    def __init__(
        self,
        repository: ImportRepository,
        storage: QuarantineObjectStorage,
        *,
        now: Clock,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._now = now

    async def __call__(
        self,
        resource_id: UUID,
        owner_hash: str,
        content_kind: ContentKind,
        parts: tuple[CompletedUploadPart, ...],
    ) -> ImportView:
        owner_hash = _validate_owner_hash(owner_hash)
        now = _validate_now(self._now())
        resource = await _get_resource(
            self._repository, resource_id, owner_hash, content_kind
        )
        status = _status(resource)
        if status in {ImportStatus.VERIFYING, ImportStatus.READY}:
            return _view(resource)
        if status is not ImportStatus.UPLOADING or resource.active_attempt is None:
            raise ImportApplicationError(ImportApplicationErrorCode.INVALID_STATE)
        attempt = resource.active_attempt
        _validate_existing_attempt(attempt, resource, content_kind)
        if attempt.upload_id is None:
            raise ImportApplicationError(ImportApplicationErrorCode.INVALID_STATE)
        if now >= attempt.expires_at:
            await self._expire(resource, attempt, owner_hash, content_kind, now)
            raise ImportApplicationError(
                ImportApplicationErrorCode.UPLOAD_SESSION_EXPIRED
            )
        _validate_completed_parts(parts, attempt.part_count)

        head = None
        try:
            await self._storage.complete_multipart_upload(
                attempt.object_key,
                attempt.upload_id,
                parts,
            )
        except MultipartUploadNotFound:
            head = await _head(self._storage, attempt.object_key)
            if head is None:
                await self._reject_incomplete(
                    resource, attempt, owner_hash, content_kind, now
                )
        except MultipartUploadRejected as error:
            await self._reject_incomplete(
                resource, attempt, owner_hash, content_kind, now, cause=error
            )
        except ImportObjectStorageError as error:
            raise ImportApplicationError(
                ImportApplicationErrorCode.STORAGE_UNAVAILABLE
            ) from error
        head = head or await _head(self._storage, attempt.object_key)
        if head is None or head.content_type != attempt.content_type:
            await self._reject_incomplete(
                resource, attempt, owner_hash, content_kind, now
            )
        if head.size_bytes != resource.declared_size_bytes:
            await _record_failure(
                self._repository,
                resource.id,
                owner_hash,
                content_kind,
                attempt.attempt,
                ImportErrorCode.SIZE_MISMATCH,
                now,
            )
            await _cleanup(
                self._storage,
                ImportCleanupRef(attempt.object_key, attempt.upload_id),
            )
            raise ImportApplicationError(ImportApplicationErrorCode.SIZE_MISMATCH)
        try:
            verifying = await self._repository.mark_verifying(
                resource.id,
                owner_hash,
                content_kind,
                attempt.attempt,
                actual_size_bytes=head.size_bytes,
                now=now,
            )
        except ImportPersistenceError as error:
            # The completed quarantine object is intentionally retained for the
            # repository recovery scan when the transaction cannot commit.
            raise _map_persistence_error(error) from error
        return _view(verifying)

    async def _expire(
        self,
        resource: ImportResourceSnapshot,
        attempt: ImportAttemptSnapshot,
        owner_hash: str,
        content_kind: ContentKind,
        now: datetime,
    ) -> None:
        try:
            await self._repository.expire_attempt(
                resource.id,
                owner_hash,
                content_kind,
                attempt.attempt,
                now=now,
            )
        except ImportPersistenceError as error:
            raise _map_persistence_error(error) from error
        await _cleanup(
            self._storage,
            ImportCleanupRef(attempt.object_key, attempt.upload_id),
        )

    async def _reject_incomplete(
        self,
        resource: ImportResourceSnapshot,
        attempt: ImportAttemptSnapshot,
        owner_hash: str,
        content_kind: ContentKind,
        now: datetime,
        *,
        cause: Exception | None = None,
    ) -> Never:
        await _record_failure(
            self._repository,
            resource.id,
            owner_hash,
            content_kind,
            attempt.attempt,
            ImportErrorCode.UPLOAD_INCOMPLETE,
            now,
        )
        await _cleanup(
            self._storage,
            ImportCleanupRef(attempt.object_key, attempt.upload_id),
        )
        error = ImportApplicationError(ImportApplicationErrorCode.UPLOAD_INCOMPLETE)
        if cause is None:
            raise error
        raise error from cause


class GetImport:
    def __init__(
        self,
        repository: ImportRepository,
        storage: QuarantineObjectStorage,
        *,
        now: Clock,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._now = now

    async def __call__(
        self,
        resource_id: UUID,
        owner_hash: str,
        content_kind: ContentKind = ContentKind.VIDEO,
    ) -> ImportView:
        owner_hash = _validate_owner_hash(owner_hash)
        resource = await _get_resource(
            self._repository,
            resource_id,
            owner_hash,
            content_kind,
        )
        attempt = resource.active_attempt
        now = _validate_now(self._now())
        if (
            _status(resource) is ImportStatus.UPLOADING
            and attempt is not None
            and now >= attempt.expires_at
        ):
            _validate_existing_attempt(attempt, resource, content_kind)
            try:
                resource = await self._repository.expire_attempt(
                    resource_id,
                    owner_hash,
                    content_kind,
                    attempt.attempt,
                    now=now,
                )
            except ImportPersistenceError as error:
                raise _map_persistence_error(error) from error
            await _cleanup(
                self._storage,
                ImportCleanupRef(attempt.object_key, attempt.upload_id),
            )
        return _view(resource)


class CancelImport:
    def __init__(
        self,
        repository: ImportRepository,
        storage: QuarantineObjectStorage,
        *,
        now: Clock,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._now = now

    async def __call__(
        self,
        resource_id: UUID,
        owner_hash: str,
        content_kind: ContentKind = ContentKind.VIDEO,
    ) -> ImportView:
        owner_hash = _validate_owner_hash(owner_hash)
        now = _validate_now(self._now())
        try:
            cancelled = await self._repository.cancel_resource(
                resource_id,
                owner_hash,
                content_kind,
                now=now,
            )
        except ImportPersistenceError as error:
            raise _map_persistence_error(error) from error
        for cleanup in cancelled.cleanup:
            _validate_cleanup_ref(cleanup, resource_id, content_kind)
            await _cleanup(self._storage, cleanup)
        return _view(cancelled.resource)


async def _get_resource(
    repository: ImportRepository,
    resource_id: UUID,
    owner_hash: str,
    content_kind: ContentKind,
) -> ImportResourceSnapshot:
    try:
        resource = await repository.get_resource(resource_id, owner_hash, content_kind)
    except ImportPersistenceError as error:
        raise _map_persistence_error(error) from error
    if resource is None or resource.owner_hash != owner_hash:
        raise ImportApplicationError(ImportApplicationErrorCode.NOT_FOUND)
    if resource.id != resource_id or resource.content_kind != content_kind.value:
        raise ImportApplicationError(ImportApplicationErrorCode.INTERNAL_ERROR)
    return resource


def _validate_reserved_attempt(
    attempt: ImportAttemptSnapshot,
    resource: ImportResourceSnapshot,
    content_kind: ContentKind,
    limits: UploadLimits,
    part_count: int,
    now: datetime,
    requested_expiry: datetime,
) -> None:
    expected_key = _expected_object_key(content_kind, resource.id, attempt.attempt)
    valid = (
        attempt.resource_id == resource.id
        and attempt.content_kind == content_kind.value
        and attempt.status == ImportStatus.UPLOADING.value
        and attempt.object_key == expected_key
        and attempt.upload_id is None
        and attempt.content_type == _resource_content_type(resource)
        and attempt.declared_size_bytes == resource.declared_size_bytes
        and attempt.part_size_bytes == limits.part_size_bytes
        and attempt.part_count == part_count
        and now < attempt.expires_at <= requested_expiry
    )
    if not valid:
        raise ImportApplicationError(ImportApplicationErrorCode.INTERNAL_ERROR)


def _validate_active_attempt(
    active: ImportAttemptSnapshot, reserved: ImportAttemptSnapshot, upload_id: str
) -> None:
    if (
        active.resource_id != reserved.resource_id
        or active.attempt != reserved.attempt
        or active.object_key != reserved.object_key
        or active.upload_id != upload_id
        or active.status != ImportStatus.UPLOADING.value
    ):
        raise ImportPersistenceConflict("activated upload attempt differs")


def _validate_existing_attempt(
    attempt: ImportAttemptSnapshot,
    resource: ImportResourceSnapshot,
    content_kind: ContentKind,
) -> None:
    valid = (
        attempt.resource_id == resource.id
        and attempt.content_kind == content_kind.value
        and attempt.attempt == resource.attempt
        and attempt.status == ImportStatus.UPLOADING.value
        and attempt.object_key
        == _expected_object_key(content_kind, resource.id, attempt.attempt)
        and attempt.content_type == _resource_content_type(resource)
        and attempt.declared_size_bytes == resource.declared_size_bytes
        and 5 * 1024**2 <= attempt.part_size_bytes <= 5 * 1024**3
        and 1 <= attempt.part_count <= 10_000
        and attempt.part_count
        == (resource.declared_size_bytes + attempt.part_size_bytes - 1)
        // attempt.part_size_bytes
        and attempt.expires_at.tzinfo is not None
        and attempt.expires_at.utcoffset() is not None
    )
    if not valid:
        raise ImportApplicationError(ImportApplicationErrorCode.INTERNAL_ERROR)


def _validate_cleanup_ref(
    cleanup: ImportCleanupRef, resource_id: UUID, content_kind: ContentKind
) -> None:
    prefix = f"quarantine/{content_kind.value}/{resource_id}/"
    relative = cleanup.object_key.removeprefix(prefix)
    parts = relative.split("/")
    if (
        not cleanup.object_key.startswith(prefix)
        or len(parts) != 2
        or not parts[0].isdigit()
        or int(parts[0]) <= 0
        or parts[1] != "source"
        or (
            cleanup.upload_id is not None
            and (
                not cleanup.upload_id
                or len(cleanup.upload_id) > 1024
                or any(ord(character) < 0x20 for character in cleanup.upload_id)
            )
        )
    ):
        raise ImportApplicationError(ImportApplicationErrorCode.INTERNAL_ERROR)


def _validate_completed_parts(
    parts: tuple[CompletedUploadPart, ...], expected_count: int
) -> None:
    if len(parts) != expected_count:
        raise ImportApplicationError(ImportApplicationErrorCode.UPLOAD_INCOMPLETE)
    numbers: set[int] = set()
    for part in parts:
        etag = part.etag.removeprefix('"').removesuffix('"')
        if (
            isinstance(part.part_number, bool)
            or not 1 <= part.part_number <= expected_count
            or part.part_number in numbers
            or re.fullmatch(r"[0-9a-fA-F]{32}", etag) is None
        ):
            raise ImportApplicationError(ImportApplicationErrorCode.UPLOAD_INCOMPLETE)
        numbers.add(part.part_number)
    if numbers != set(range(1, expected_count + 1)):
        raise ImportApplicationError(ImportApplicationErrorCode.UPLOAD_INCOMPLETE)


async def _record_failure(
    repository: ImportRepository,
    resource_id: UUID,
    owner_hash: str,
    content_kind: ContentKind,
    attempt: int,
    error_code: ImportErrorCode,
    now: datetime,
) -> None:
    try:
        await repository.fail_attempt(
            resource_id,
            owner_hash,
            content_kind,
            attempt,
            error_code=error_code,
            now=now,
        )
    except ImportPersistenceError as error:
        raise _map_persistence_error(error) from error


async def _cleanup(storage: QuarantineObjectStorage, cleanup: ImportCleanupRef) -> None:
    if cleanup.upload_id is not None:
        with suppress(ImportObjectStorageError):
            await storage.abort_multipart_upload(cleanup.object_key, cleanup.upload_id)
    with suppress(ImportObjectStorageError):
        await storage.delete(cleanup.object_key)


async def _head(storage: QuarantineObjectStorage, object_key: str) -> ObjectHead | None:
    try:
        return await storage.stat(object_key)
    except ImportObjectStorageError as error:
        raise ImportApplicationError(
            ImportApplicationErrorCode.STORAGE_UNAVAILABLE
        ) from error


def _validate_saved_resource(
    command: ImportResourceCreate, resource: ImportResourceSnapshot
) -> None:
    valid = (
        resource.owner_hash == command.owner_hash
        and resource.content_kind == command.content_kind.value
        and resource.source_format == command.source_format.value
        and resource.declared_size_bytes == command.declared_size_bytes
        and resource.declared_sha256 == command.declared_sha256
        and resource.declared_origin == command.declared_origin.value
    )
    if not valid:
        raise ImportApplicationError(ImportApplicationErrorCode.INTERNAL_ERROR)


def _view(resource: ImportResourceSnapshot) -> ImportView:
    try:
        return ImportView(
            id=resource.id,
            content_kind=ContentKind(resource.content_kind),
            source_format=ImportSourceFormat(resource.source_format),
            display_name=resource.display_name,
            declared_size_bytes=resource.declared_size_bytes,
            status=ImportStatus(resource.status),
            attempt=resource.attempt,
            error_code=(
                ImportErrorCode(resource.error_code)
                if resource.error_code is not None
                else None
            ),
            version=resource.version,
            created_at=resource.created_at,
            updated_at=resource.updated_at,
            finished_at=resource.finished_at,
            declared_origin=DeclaredOrigin(resource.declared_origin),
        )
    except ValueError as error:
        raise ImportApplicationError(
            ImportApplicationErrorCode.INTERNAL_ERROR
        ) from error


def _status(resource: ImportResourceSnapshot) -> ImportStatus:
    try:
        return ImportStatus(resource.status)
    except ValueError as error:
        raise ImportApplicationError(
            ImportApplicationErrorCode.INTERNAL_ERROR
        ) from error


def _resource_content_type(resource: ImportResourceSnapshot) -> str:
    try:
        source_format = ImportSourceFormat(resource.source_format)
    except ValueError as error:
        raise ImportApplicationError(
            ImportApplicationErrorCode.INTERNAL_ERROR
        ) from error
    if source_format.content_kind.value != resource.content_kind:
        raise ImportApplicationError(ImportApplicationErrorCode.INTERNAL_ERROR)
    return source_format.content_type


def _expected_object_key(
    content_kind: ContentKind, resource_id: UUID, attempt: int
) -> str:
    try:
        return quarantine_object_key(content_kind, resource_id, attempt)
    except ValueError as error:
        raise ImportApplicationError(
            ImportApplicationErrorCode.INTERNAL_ERROR
        ) from error


def _display_name(value: str, source_format: ImportSourceFormat) -> str:
    if not isinstance(value, str):
        _invalid_request()
    base_name = re.split(r"[\\/]", value)[-1]
    cleaned = re.sub(r'[:*?"<>|\x00-\x1f\x7f]', "", base_name).strip()
    cleaned = cleaned[:128].rstrip(".")
    if (
        not cleaned
        or PurePosixPath(cleaned).suffix.casefold()
        not in _FORMAT_SUFFIXES[source_format]
    ):
        _invalid_request()
    return cleaned


def _validate_owner_hash(value: str) -> str:
    if _OWNER_HASH.fullmatch(value) is None:
        _invalid_request()
    return value


def _validate_idempotency_key(value: str) -> str:
    if not value or len(value) > 128 or value != value.strip():
        _invalid_request()
    return value


def _validate_now(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return timezone-aware datetime")
    return value


def _map_persistence_error(error: ImportPersistenceError) -> ImportApplicationError:
    if isinstance(error, ImportPersistenceNotFound):
        code = ImportApplicationErrorCode.NOT_FOUND
    elif isinstance(error, ImportPersistenceIdempotencyConflict):
        code = ImportApplicationErrorCode.IDEMPOTENCY_CONFLICT
    elif isinstance(error, ImportPersistenceConflict):
        code = ImportApplicationErrorCode.INVALID_STATE
    else:
        code = ImportApplicationErrorCode.INTERNAL_ERROR
    return ImportApplicationError(code)


def _invalid_request() -> Never:
    raise ImportApplicationError(ImportApplicationErrorCode.INVALID_REQUEST)
