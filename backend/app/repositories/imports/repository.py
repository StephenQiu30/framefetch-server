"""Transactional persistence for browser MP4 import resources."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import as_utc
from app.models import (
    ArtifactRow,
    DownloadJobRow,
    MediaImportAttemptRow,
    MediaImportRow,
    OutboxEventRow,
)
from app.repositories.quota_admission import lock_admission, reserve
from app.repositories.repository_base import RepositoryBase
from app.repositories.watermark import enqueue_automatic
from app.services.import_execution.models import (
    ImportVerificationClaim,
    VerifiedImportArtifact,
)
from app.services.imports.errors import (
    ImportPersistenceConflict,
    ImportPersistenceIdempotencyConflict,
    ImportPersistenceNotFound,
)
from app.services.imports.events import (
    CONTENT_IMPORT_VERIFY_REQUESTED,
    import_verify_requested_payload,
)
from app.services.imports.models import (
    BeginUploadAttemptResult,
    CancelImportResult,
    ImportAttemptSnapshot,
    ImportCleanupRef,
    ImportResourceCreate,
    ImportResourceSaveResult,
    ImportResourceSnapshot,
)
from app.services.imports.rules.enums import (
    ContentKind,
    ImportErrorCode,
    ImportSourceFormat,
    ImportStatus,
)
from app.services.imports.rules.keys import quarantine_object_key


class SqlAlchemyMediaImportRepository(RepositoryBase):
    """Store the video-import aggregate and its download projection atomically."""

    async def create_resource(
        self, command: ImportResourceCreate, *, now: datetime
    ) -> ImportResourceSaveResult:
        _require_video_create(command)
        async with self._sessions() as session:
            try:
                async with session.begin():
                    await lock_admission(session, command.owner_hash)
                    existing = await session.scalar(self._idempotency_query(command))
                    if existing is not None:
                        return await self._idempotent_result(session, existing, command)
                    await reserve(
                        session,
                        self._quota_policy,
                        owner_hash=command.owner_hash,
                        resource_id=command.id,
                        kind="media_import",
                        size_bytes=command.declared_size_bytes,
                        now=now,
                        quota=command.quota,
                    )
                    job = DownloadJobRow(
                        id=command.id,
                        source_kind="browser_import",
                        inspection_id=None,
                        format_id=None,
                        owner_hash=command.owner_hash,
                        idempotency_key=f"browser-import:{command.id}",
                        request_fingerprint=command.request_fingerprint,
                        semantic_plan={
                            "source_kind": "browser_import",
                            "container": "mp4",
                            "declared_origin": command.declared_origin.value,
                            "remove_watermark": command.remove_watermark,
                        },
                        status="running",
                        stage="downloading",
                        stage_rank=2,
                        progress=0,
                        attempt=0,
                        max_attempts=1,
                        version=0,
                        started_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    row = MediaImportRow(
                        id=command.id,
                        owner_hash=command.owner_hash,
                        idempotency_key=command.idempotency_key,
                        request_fingerprint=command.request_fingerprint,
                        source_format=command.source_format.value,
                        display_name=command.display_name,
                        content_type=command.content_type,
                        declared_size_bytes=command.declared_size_bytes,
                        declared_sha256=command.declared_sha256,
                        rights_statement_version=command.rights_statement_version,
                        declared_origin=command.declared_origin.value,
                        status=ImportStatus.UPLOADING.value,
                        attempt=0,
                        version=0,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add_all((job, row))
                    await session.flush()
                    result = ImportResourceSaveResult(
                        _resource_snapshot(row, None), created=True
                    )
                return result
            except IntegrityError as exc:
                await session.rollback()
                existing = await session.scalar(self._idempotency_query(command))
                if existing is None:
                    raise
                try:
                    return await self._idempotent_result(session, existing, command)
                except ImportPersistenceIdempotencyConflict as conflict:
                    raise conflict from exc

    async def get_resource(
        self, resource_id: UUID, owner_hash: str, content_kind: ContentKind
    ) -> ImportResourceSnapshot | None:
        if content_kind is not ContentKind.VIDEO:
            return None
        async with self._sessions() as session:
            row = await session.scalar(
                select(MediaImportRow).where(
                    MediaImportRow.id == resource_id,
                    MediaImportRow.owner_hash == owner_hash,
                )
            )
            if row is None:
                return None
            attempt = await _current_attempt(session, row)
            return _resource_snapshot(row, _visible_attempt(attempt))

    async def begin_upload_attempt(
        self,
        resource_id: UUID,
        owner_hash: str,
        content_kind: ContentKind,
        *,
        part_size_bytes: int,
        part_count: int,
        expires_at: datetime,
        now: datetime,
    ) -> BeginUploadAttemptResult:
        _require_video_kind(content_kind)
        _validate_part_plan(part_size_bytes, part_count, expires_at, now)
        async with self._sessions() as session, session.begin():
            row = await _lock_resource(session, resource_id, owner_hash)
            if row.status != ImportStatus.UPLOADING.value:
                raise ImportPersistenceConflict("media import is not uploadable")
            superseded: tuple[ImportCleanupRef, ...] = ()
            current = await _current_attempt(session, row, for_update=True)
            if current is not None and current.status == ImportStatus.UPLOADING.value:
                current.status = ImportStatus.EXPIRED.value
                current.error_code = ImportErrorCode.UPLOAD_SESSION_EXPIRED.value
                current.finished_at = now
                current.updated_at = now
                superseded = (ImportCleanupRef(current.object_key, current.upload_id),)
            next_attempt = row.attempt + 1
            attempt = MediaImportAttemptRow(
                resource_id=row.id,
                attempt=next_attempt,
                status=ImportStatus.UPLOADING.value,
                object_key=quarantine_object_key(
                    ContentKind.VIDEO, row.id, next_attempt
                ),
                upload_id=None,
                content_type=row.content_type,
                declared_size_bytes=row.declared_size_bytes,
                part_size_bytes=part_size_bytes,
                part_count=part_count,
                expires_at=expires_at,
                created_at=now,
                updated_at=now,
            )
            session.add(attempt)
            row.attempt = next_attempt
            row.error_code = None
            row.version += 1
            row.updated_at = now
            job = await _lock_job(session, row.id)
            _set_job_uploading(job, now)
            await session.flush()
            return BeginUploadAttemptResult(_attempt_snapshot(attempt), superseded)

    async def activate_upload_attempt(
        self,
        resource_id: UUID,
        owner_hash: str,
        content_kind: ContentKind,
        attempt: int,
        *,
        upload_id: str,
        now: datetime,
    ) -> ImportAttemptSnapshot:
        _require_video_kind(content_kind)
        if not _valid_upload_id(upload_id):
            raise ImportPersistenceConflict("invalid multipart upload id")
        async with self._sessions() as session, session.begin():
            row = await _lock_resource(session, resource_id, owner_hash)
            current = await _lock_attempt(session, row, attempt)
            if (
                row.status != ImportStatus.UPLOADING.value
                or current.status != ImportStatus.UPLOADING.value
                or row.attempt != attempt
                or as_utc(current.expires_at) <= as_utc(now)
            ):
                raise ImportPersistenceConflict("upload attempt is no longer active")
            if current.upload_id is not None and current.upload_id != upload_id:
                raise ImportPersistenceConflict("upload attempt is already activated")
            current.upload_id = upload_id
            current.updated_at = now
            row.updated_at = now
            await session.flush()
            return _attempt_snapshot(current)

    async def mark_verifying(
        self,
        resource_id: UUID,
        owner_hash: str,
        content_kind: ContentKind,
        attempt: int,
        *,
        actual_size_bytes: int,
        now: datetime,
    ) -> ImportResourceSnapshot:
        _require_video_kind(content_kind)
        async with self._sessions() as session, session.begin():
            row = await _lock_resource(session, resource_id, owner_hash)
            current = await _lock_attempt(session, row, attempt)
            if row.status == ImportStatus.VERIFYING.value:
                if (
                    row.attempt != attempt
                    or current.status != ImportStatus.VERIFYING.value
                    or current.actual_size_bytes != actual_size_bytes
                ):
                    raise ImportPersistenceConflict(
                        "completed upload differs from stored verification"
                    )
                return _resource_snapshot(row, current)
            if (
                row.status != ImportStatus.UPLOADING.value
                or row.attempt != attempt
                or current.status != ImportStatus.UPLOADING.value
                or current.upload_id is None
                or actual_size_bytes != row.declared_size_bytes
            ):
                raise ImportPersistenceConflict("upload attempt cannot be verified")
            current.status = ImportStatus.VERIFYING.value
            current.actual_size_bytes = actual_size_bytes
            current.completed_at = now
            current.error_code = None
            current.updated_at = now
            row.status = ImportStatus.VERIFYING.value
            row.error_code = None
            row.version += 1
            row.updated_at = now
            job = await _lock_job(session, row.id)
            job.status = "running"
            job.stage = "verifying"
            job.stage_rank = 4
            job.progress = max(job.progress, 50)
            job.version += 1
            job.error_code = None
            job.error_message = None
            job.updated_at = now
            session.add(
                OutboxEventRow(
                    id=uuid4(),
                    aggregate_type="media_import",
                    aggregate_id=row.id,
                    event_type=CONTENT_IMPORT_VERIFY_REQUESTED,
                    payload=import_verify_requested_payload(
                        row.id, ContentKind.VIDEO, attempt, row.version
                    ),
                    available_at=now,
                    created_at=now,
                )
            )
            await session.flush()
            return _resource_snapshot(row, current)

    async def fail_attempt(
        self,
        resource_id: UUID,
        owner_hash: str,
        content_kind: ContentKind,
        attempt: int,
        *,
        error_code: ImportErrorCode,
        now: datetime,
    ) -> ImportResourceSnapshot:
        _require_video_kind(content_kind)
        async with self._sessions() as session, session.begin():
            row = await _lock_resource(session, resource_id, owner_hash)
            current = await _lock_attempt(session, row, attempt)
            if (
                current.status == ImportStatus.FAILED.value
                and current.error_code == error_code.value
                and row.error_code == error_code.value
            ):
                return _resource_snapshot(row, None)
            if (
                row.attempt != attempt
                or row.status != ImportStatus.UPLOADING.value
                or current.status != ImportStatus.UPLOADING.value
            ):
                raise ImportPersistenceConflict("upload attempt cannot be failed")
            current.status = ImportStatus.FAILED.value
            current.error_code = error_code.value
            current.finished_at = now
            current.updated_at = now
            row.status = (
                ImportStatus.UPLOADING.value
                if error_code.retryable
                else ImportStatus.FAILED.value
            )
            row.error_code = error_code.value
            row.finished_at = None if error_code.retryable else now
            row.version += 1
            row.updated_at = now
            job = await _lock_job(session, row.id)
            if error_code.retryable:
                _set_job_uploading(job, now, error_code="storage_unavailable")
            else:
                _set_job_failed(job, now, error_code="media_validation_failed")
            await session.flush()
            return _resource_snapshot(row, None)

    async def expire_attempt(
        self,
        resource_id: UUID,
        owner_hash: str,
        content_kind: ContentKind,
        attempt: int,
        *,
        now: datetime,
    ) -> ImportResourceSnapshot:
        _require_video_kind(content_kind)
        async with self._sessions() as session, session.begin():
            row = await _lock_resource(session, resource_id, owner_hash)
            current = await _lock_attempt(session, row, attempt)
            if (
                current.status == ImportStatus.EXPIRED.value
                and row.status == ImportStatus.UPLOADING.value
            ):
                return _resource_snapshot(row, None)
            if (
                row.status != ImportStatus.UPLOADING.value
                or row.attempt != attempt
                or current.status != ImportStatus.UPLOADING.value
                or as_utc(current.expires_at) > as_utc(now)
            ):
                raise ImportPersistenceConflict("upload attempt cannot be expired")
            current.status = ImportStatus.EXPIRED.value
            current.error_code = ImportErrorCode.UPLOAD_SESSION_EXPIRED.value
            current.finished_at = now
            current.updated_at = now
            row.error_code = ImportErrorCode.UPLOAD_SESSION_EXPIRED.value
            row.version += 1
            row.updated_at = now
            job = await _lock_job(session, row.id)
            _set_job_uploading(job, now)
            await session.flush()
            return _resource_snapshot(row, None)

    async def cancel_resource(
        self,
        resource_id: UUID,
        owner_hash: str,
        content_kind: ContentKind,
        *,
        now: datetime,
    ) -> CancelImportResult:
        _require_video_kind(content_kind)
        async with self._sessions() as session, session.begin():
            row = await _lock_resource(session, resource_id, owner_hash)
            current = await _current_attempt(session, row, for_update=True)
            if row.status == ImportStatus.CANCELLED.value:
                return CancelImportResult(
                    _resource_snapshot(row, None), _cleanup_refs(current)
                )
            if row.status not in {
                ImportStatus.UPLOADING.value,
                ImportStatus.VERIFYING.value,
            }:
                raise ImportPersistenceConflict("terminal media import cannot cancel")
            if current is not None and current.status in {
                ImportStatus.UPLOADING.value,
                ImportStatus.VERIFYING.value,
            }:
                current.status = ImportStatus.CANCELLED.value
                current.error_code = None
                current.finished_at = now
                current.updated_at = now
            row.status = ImportStatus.CANCELLED.value
            row.error_code = None
            row.finished_at = now
            row.version += 1
            row.updated_at = now
            job = await _lock_job(session, row.id)
            job.status = "cancelled"
            job.stage = None
            job.stage_rank = 0
            job.version += 1
            job.cancel_requested_at = now
            job.finished_at = now
            job.error_code = "cancelled"
            job.error_message = None
            job.lease_owner = None
            job.lease_expires_at = None
            job.updated_at = now
            await session.flush()
            return CancelImportResult(
                _resource_snapshot(row, None), _cleanup_refs(current)
            )

    async def claim_verification(
        self,
        resource_id: UUID,
        content_kind: ContentKind,
        attempt: int,
        expected_version: int,
        *,
        worker_id: str,
        now: datetime,
        lease_for: timedelta,
    ) -> ImportVerificationClaim | None:
        _require_verification_arguments(
            content_kind, attempt, expected_version, worker_id, lease_for
        )
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(MediaImportRow)
                .where(MediaImportRow.id == resource_id)
                .with_for_update()
            )
            if row is None or (
                row.status != ImportStatus.VERIFYING.value
                or row.attempt != attempt
                or row.version != expected_version
            ):
                return None
            current = await _lock_attempt(session, row, attempt)
            if current.status != ImportStatus.VERIFYING.value:
                return None
            if current.lease_expires_at is not None and as_utc(
                current.lease_expires_at
            ) > as_utc(now):
                return None
            job = await _lock_job(session, row.id)
            if job.status != "running":
                return None
            current.lease_owner = worker_id
            current.lease_expires_at = now + lease_for
            current.heartbeat_at = now
            current.updated_at = now
            job.attempt = attempt
            job.lease_owner = worker_id
            job.lease_expires_at = now + lease_for
            job.heartbeat_at = now
            job.stage = "verifying"
            job.stage_rank = 4
            job.progress = max(job.progress, 55)
            job.version += 1
            job.updated_at = now
            await session.flush()
            return _verification_claim(row, current)

    async def heartbeat_verification(
        self,
        resource_id: UUID,
        attempt: int,
        *,
        worker_id: str,
        stage: str,
        progress: int,
        now: datetime,
        lease_for: timedelta,
    ) -> bool:
        _require_heartbeat_arguments(attempt, worker_id, stage, progress, lease_for)
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(MediaImportRow)
                .where(MediaImportRow.id == resource_id)
                .with_for_update()
            )
            if row is None or (
                row.status != ImportStatus.VERIFYING.value or row.attempt != attempt
            ):
                return False
            current = await _lock_attempt(session, row, attempt)
            job = await _lock_job(session, row.id)
            if not _owns_verification(current, job, worker_id, attempt, now):
                return False
            current.heartbeat_at = now
            current.lease_expires_at = now + lease_for
            current.updated_at = now
            stage_rank = 4 if stage == "verifying" else 5
            if job.stage_rank <= stage_rank:
                job.stage = stage
                job.stage_rank = stage_rank
            job.progress = max(job.progress, progress)
            job.heartbeat_at = now
            job.lease_expires_at = now + lease_for
            job.version += 1
            job.updated_at = now
            await session.flush()
            return True

    async def complete_verification(
        self,
        claim: ImportVerificationClaim,
        artifact: VerifiedImportArtifact,
        *,
        worker_id: str,
        bucket: str,
        now: datetime,
    ) -> None:
        _validate_verified_artifact(artifact, bucket)
        object_key = _final_object_key(claim)
        async with self._sessions() as session, session.begin():
            owner = await session.scalar(
                select(DownloadJobRow.owner_hash).where(
                    DownloadJobRow.id == claim.resource_id
                )
            )
            if owner is not None:
                await lock_admission(session, owner)
            row = await session.scalar(
                select(MediaImportRow)
                .where(MediaImportRow.id == claim.resource_id)
                .with_for_update()
            )
            if row is None:
                raise ImportPersistenceNotFound("media import does not exist")
            if row.status == ImportStatus.READY.value:
                stored = await session.scalar(
                    select(ArtifactRow).where(ArtifactRow.job_id == row.id)
                )
                if stored is None or not _artifact_matches(
                    stored, claim, artifact, bucket, object_key
                ):
                    raise ImportPersistenceConflict(
                        "completed media import artifact is inconsistent"
                    )
                return
            current = await _lock_attempt(session, row, claim.attempt)
            job = await _lock_job(session, row.id)
            if (
                row.status != ImportStatus.VERIFYING.value
                or row.attempt != claim.attempt
                or row.version != claim.version
                or current.status != ImportStatus.VERIFYING.value
                or not _owns_verification(current, job, worker_id, claim.attempt, now)
                or job.stage != "uploading"
            ):
                raise ImportPersistenceConflict(
                    "media import verification lease was lost"
                )
            stored = ArtifactRow(
                id=uuid4(),
                job_id=row.id,
                attempt=claim.attempt,
                bucket=bucket,
                object_key=object_key,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
                duration_ms=artifact.duration_ms,
                container=artifact.container,
                content_type=artifact.content_type,
                media_metadata=artifact.media_metadata,
                created_at=now,
            )
            session.add(stored)
            current.status = ImportStatus.READY.value
            current.error_code = None
            current.finished_at = now
            current.updated_at = now
            _clear_attempt_lease(current, heartbeat_at=now)
            row.status = ImportStatus.READY.value
            row.error_code = None
            row.finished_at = now
            row.version += 1
            row.updated_at = now
            job.status = "succeeded"
            job.stage = None
            job.stage_rank = 0
            job.progress = 100
            job.version += 1
            job.finished_at = now
            job.retry_at = None
            job.error_code = None
            job.error_message = None
            job.lease_owner = None
            job.lease_expires_at = None
            job.heartbeat_at = now
            job.updated_at = now
            await session.flush()
            if job.semantic_plan.get("remove_watermark") is True:
                await enqueue_automatic(session, job, stored, self._quota_policy)

    async def fail_verification(
        self,
        claim: ImportVerificationClaim,
        error_code: ImportErrorCode,
        *,
        worker_id: str,
        now: datetime,
    ) -> None:
        if error_code not in {
            ImportErrorCode.SIZE_MISMATCH,
            ImportErrorCode.SHA256_MISMATCH,
            ImportErrorCode.VIDEO_INVALID,
        }:
            raise ValueError("unsupported terminal video verification error")
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(MediaImportRow)
                .where(MediaImportRow.id == claim.resource_id)
                .with_for_update()
            )
            if row is None:
                raise ImportPersistenceNotFound("media import does not exist")
            if (
                row.status == ImportStatus.FAILED.value
                and row.error_code == error_code.value
            ):
                return
            current = await _lock_attempt(session, row, claim.attempt)
            job = await _lock_job(session, row.id)
            if (
                row.status != ImportStatus.VERIFYING.value
                or row.attempt != claim.attempt
                or row.version != claim.version
                or current.status != ImportStatus.VERIFYING.value
                or not _owns_verification(current, job, worker_id, claim.attempt, now)
            ):
                raise ImportPersistenceConflict(
                    "media import verification lease was lost"
                )
            current.status = ImportStatus.FAILED.value
            current.error_code = error_code.value
            current.finished_at = now
            current.updated_at = now
            _clear_attempt_lease(current, heartbeat_at=now)
            row.status = ImportStatus.FAILED.value
            row.error_code = error_code.value
            row.finished_at = now
            row.version += 1
            row.updated_at = now
            _set_job_failed(job, now, error_code="media_validation_failed")
            job.attempt = claim.attempt
            job.heartbeat_at = now
            job.lease_owner = None
            job.lease_expires_at = None
            await session.flush()

    async def recover_expired_verifications(
        self, now: datetime, *, limit: int
    ) -> tuple[UUID, ...]:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        async with self._sessions() as session, session.begin():
            statement = (
                select(MediaImportRow, MediaImportAttemptRow)
                .join(
                    MediaImportAttemptRow,
                    (MediaImportAttemptRow.resource_id == MediaImportRow.id)
                    & (MediaImportAttemptRow.attempt == MediaImportRow.attempt),
                )
                .where(
                    MediaImportRow.status == ImportStatus.VERIFYING.value,
                    MediaImportAttemptRow.status == ImportStatus.VERIFYING.value,
                    MediaImportAttemptRow.lease_expires_at.is_not(None),
                    MediaImportAttemptRow.lease_expires_at <= now,
                )
                .order_by(
                    MediaImportAttemptRow.lease_expires_at,
                    MediaImportAttemptRow.resource_id,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            pairs = tuple((await session.execute(statement)).all())
            recovered: list[UUID] = []
            for row, current in pairs:
                job = await _lock_job(session, row.id)
                _clear_attempt_lease(current, heartbeat_at=current.heartbeat_at)
                current.updated_at = now
                job.lease_owner = None
                job.lease_expires_at = None
                job.stage = "verifying"
                job.stage_rank = 4
                job.progress = max(job.progress, 50)
                job.version += 1
                job.updated_at = now
                session.add(
                    OutboxEventRow(
                        id=uuid4(),
                        aggregate_type="media_import",
                        aggregate_id=row.id,
                        event_type=CONTENT_IMPORT_VERIFY_REQUESTED,
                        payload=import_verify_requested_payload(
                            row.id, ContentKind.VIDEO, row.attempt, row.version
                        ),
                        available_at=now,
                        created_at=now,
                    )
                )
                recovered.append(row.id)
            await session.flush()
            return tuple(recovered)

    async def expected_artifact_object_keys(self) -> frozenset[str]:
        async with self._sessions() as session:
            keys = await session.scalars(
                select(ArtifactRow.object_key).where(ArtifactRow.deleted_at.is_(None))
            )
            return frozenset(keys)

    @staticmethod
    def _idempotency_query(
        command: ImportResourceCreate,
    ) -> Select[tuple[MediaImportRow]]:
        return select(MediaImportRow).where(
            MediaImportRow.owner_hash == command.owner_hash,
            MediaImportRow.idempotency_key == command.idempotency_key,
        )

    @staticmethod
    async def _idempotent_result(
        session: AsyncSession,
        row: MediaImportRow,
        command: ImportResourceCreate,
    ) -> ImportResourceSaveResult:
        if row.request_fingerprint != command.request_fingerprint:
            raise ImportPersistenceIdempotencyConflict(
                "media import idempotency key already used"
            )
        attempt = await _current_attempt(session, row)
        return ImportResourceSaveResult(
            _resource_snapshot(row, _visible_attempt(attempt)), created=False
        )


def _require_video_create(command: ImportResourceCreate) -> None:
    if (
        command.content_kind is not ContentKind.VIDEO
        or command.source_format is not ImportSourceFormat.MP4
        or command.content_type != ImportSourceFormat.MP4.content_type
    ):
        raise ImportPersistenceConflict(
            "media import repository only accepts browser MP4 resources"
        )


def _require_video_kind(content_kind: ContentKind) -> None:
    if content_kind is not ContentKind.VIDEO:
        raise ImportPersistenceNotFound("media import does not exist")


def _validate_part_plan(
    part_size_bytes: int, part_count: int, expires_at: datetime, now: datetime
) -> None:
    if (
        isinstance(part_size_bytes, bool)
        or not 5 * 1024**2 <= part_size_bytes <= 5 * 1024**3
        or isinstance(part_count, bool)
        or not 1 <= part_count <= 10_000
        or as_utc(expires_at) <= as_utc(now)
    ):
        raise ImportPersistenceConflict("invalid upload part plan")


def _valid_upload_id(upload_id: str) -> bool:
    return (
        bool(upload_id)
        and len(upload_id) <= 1024
        and all(ord(character) >= 0x20 for character in upload_id)
    )


async def _lock_resource(
    session: AsyncSession, resource_id: UUID, owner_hash: str
) -> MediaImportRow:
    row = await session.scalar(
        select(MediaImportRow)
        .where(
            MediaImportRow.id == resource_id,
            MediaImportRow.owner_hash == owner_hash,
        )
        .with_for_update()
    )
    if row is None:
        raise ImportPersistenceNotFound("media import does not exist")
    return row


async def _lock_job(session: AsyncSession, resource_id: UUID) -> DownloadJobRow:
    row = await session.scalar(
        select(DownloadJobRow)
        .where(
            DownloadJobRow.id == resource_id,
            DownloadJobRow.source_kind == "browser_import",
        )
        .with_for_update()
    )
    if row is None:
        raise ImportPersistenceConflict("browser import download job is missing")
    return row


async def _lock_attempt(
    session: AsyncSession, resource: MediaImportRow, attempt: int
) -> MediaImportAttemptRow:
    row = await session.scalar(
        select(MediaImportAttemptRow)
        .where(
            MediaImportAttemptRow.resource_id == resource.id,
            MediaImportAttemptRow.attempt == attempt,
        )
        .with_for_update()
    )
    if row is None:
        raise ImportPersistenceConflict("media import attempt does not exist")
    return row


async def _current_attempt(
    session: AsyncSession, resource: MediaImportRow, *, for_update: bool = False
) -> MediaImportAttemptRow | None:
    if resource.attempt <= 0:
        return None
    statement: Select[tuple[MediaImportAttemptRow]] = select(
        MediaImportAttemptRow
    ).where(
        MediaImportAttemptRow.resource_id == resource.id,
        MediaImportAttemptRow.attempt == resource.attempt,
    )
    if for_update:
        statement = statement.with_for_update()
    return cast(MediaImportAttemptRow | None, await session.scalar(statement))


def _visible_attempt(
    row: MediaImportAttemptRow | None,
) -> MediaImportAttemptRow | None:
    if row is None or row.status not in {
        ImportStatus.UPLOADING.value,
        ImportStatus.VERIFYING.value,
    }:
        return None
    return row


def _resource_snapshot(
    row: MediaImportRow, attempt: MediaImportAttemptRow | None
) -> ImportResourceSnapshot:
    return ImportResourceSnapshot(
        id=row.id,
        owner_hash=row.owner_hash,
        content_kind=ContentKind.VIDEO.value,
        source_format=row.source_format,
        display_name=row.display_name,
        declared_size_bytes=row.declared_size_bytes,
        declared_sha256=row.declared_sha256,
        status=row.status,
        attempt=row.attempt,
        error_code=row.error_code,
        version=row.version,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
        finished_at=(None if row.finished_at is None else as_utc(row.finished_at)),
        declared_origin=row.declared_origin,
        active_attempt=None if attempt is None else _attempt_snapshot(attempt),
    )


def _attempt_snapshot(row: MediaImportAttemptRow) -> ImportAttemptSnapshot:
    return ImportAttemptSnapshot(
        resource_id=row.resource_id,
        content_kind=ContentKind.VIDEO.value,
        attempt=row.attempt,
        status=row.status,
        object_key=row.object_key,
        upload_id=row.upload_id,
        content_type=row.content_type,
        declared_size_bytes=row.declared_size_bytes,
        part_size_bytes=row.part_size_bytes,
        part_count=row.part_count,
        expires_at=as_utc(row.expires_at),
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
    )


def _cleanup_refs(
    row: MediaImportAttemptRow | None,
) -> tuple[ImportCleanupRef, ...]:
    if row is None:
        return ()
    return (ImportCleanupRef(row.object_key, row.upload_id),)


def _set_job_uploading(
    row: DownloadJobRow, now: datetime, *, error_code: str | None = None
) -> None:
    row.status = "running"
    row.stage = "downloading"
    row.stage_rank = 2
    row.progress = 0
    row.version += 1
    row.finished_at = None
    row.error_code = error_code
    row.error_message = None
    row.updated_at = now


def _set_job_failed(row: DownloadJobRow, now: datetime, *, error_code: str) -> None:
    row.status = "failed"
    row.stage = None
    row.stage_rank = 0
    row.version += 1
    row.finished_at = now
    row.error_code = error_code
    row.error_message = None
    row.updated_at = now


def _require_verification_arguments(
    content_kind: ContentKind,
    attempt: int,
    expected_version: int,
    worker_id: str,
    lease_for: timedelta,
) -> None:
    if content_kind is not ContentKind.VIDEO:
        raise ValueError("media verification only accepts video")
    if (
        isinstance(attempt, bool)
        or attempt < 1
        or isinstance(expected_version, bool)
        or expected_version < 0
        or not worker_id.strip()
        or len(worker_id) > 128
        or lease_for.total_seconds() <= 0
    ):
        raise ValueError("invalid media verification claim")


def _require_heartbeat_arguments(
    attempt: int,
    worker_id: str,
    stage: str,
    progress: int,
    lease_for: timedelta,
) -> None:
    if (
        isinstance(attempt, bool)
        or attempt < 1
        or not worker_id.strip()
        or len(worker_id) > 128
        or stage not in {"verifying", "uploading"}
        or isinstance(progress, bool)
        or not 0 <= progress <= 100
        or lease_for.total_seconds() <= 0
    ):
        raise ValueError("invalid media verification heartbeat")


def _owns_verification(
    current: MediaImportAttemptRow,
    job: DownloadJobRow,
    worker_id: str,
    attempt: int,
    now: datetime,
) -> bool:
    return bool(
        current.lease_owner == worker_id
        and current.lease_expires_at is not None
        and as_utc(current.lease_expires_at) > as_utc(now)
        and job.status == "running"
        and job.source_kind == "browser_import"
        and job.attempt == attempt
        and job.lease_owner == worker_id
        and job.lease_expires_at is not None
        and as_utc(job.lease_expires_at) > as_utc(now)
    )


def _clear_attempt_lease(
    row: MediaImportAttemptRow, *, heartbeat_at: datetime | None
) -> None:
    row.lease_owner = None
    row.lease_expires_at = None
    row.heartbeat_at = heartbeat_at


def _verification_claim(
    row: MediaImportRow, current: MediaImportAttemptRow
) -> ImportVerificationClaim:
    return ImportVerificationClaim(
        resource_id=row.id,
        content_kind=ContentKind.VIDEO,
        source_format=ImportSourceFormat(row.source_format),
        attempt=current.attempt,
        version=row.version,
        object_key=current.object_key,
        declared_size_bytes=row.declared_size_bytes,
        declared_sha256=row.declared_sha256,
        owner_hash=row.owner_hash,
    )


def _final_object_key(claim: ImportVerificationClaim) -> str:
    if (
        claim.content_kind is not ContentKind.VIDEO
        or claim.source_format is not ImportSourceFormat.MP4
        or claim.attempt < 1
    ):
        raise ValueError("invalid media artifact identity")
    return f"downloads/{claim.resource_id}/{claim.attempt}/video.mp4"


def _validate_verified_artifact(
    artifact: VerifiedImportArtifact,
    bucket: str,
) -> None:
    if (
        not bucket.strip()
        or len(bucket) > 128
        or re.fullmatch(r"[0-9a-f]{64}", artifact.sha256) is None
        or artifact.size_bytes <= 0
        or artifact.duration_ms <= 0
        or artifact.container != "mp4"
        or artifact.content_type != "video/mp4"
    ):
        raise ValueError("invalid verified media artifact")


def _artifact_matches(
    row: ArtifactRow,
    claim: ImportVerificationClaim,
    artifact: VerifiedImportArtifact,
    bucket: str,
    object_key: str,
) -> bool:
    return (
        row.attempt == claim.attempt
        and row.bucket == bucket
        and row.object_key == object_key
        and row.sha256 == artifact.sha256
        and row.size_bytes == artifact.size_bytes
        and row.duration_ms == artifact.duration_ms
        and row.container == artifact.container
        and row.content_type == artifact.content_type
    )
