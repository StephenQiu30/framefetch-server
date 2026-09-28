from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import UUID

from app.services.downloads.download_models import (
    ArtifactSnapshot,
    DownloadCleanupRef,
    DownloadCreate,
    DownloadDeletionPlan,
    DownloadPresentationSnapshot,
    JobSaveResult,
    JobSnapshot,
)
from app.services.downloads.errors import PersistenceIdempotencyConflict
from app.services.downloads.inspection_models import (
    EncryptedUrl,
    FormatSnapshot,
    InspectionCreate,
    InspectionSaveResult,
    InspectionSnapshot,
    RunnerInspection,
)
from app.services.downloads.thumbnail import ThumbnailObject, ThumbnailSource
from app.services.provider_access import ProviderAccessPolicy


class FakeValidator:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def validate(self, url: str) -> str:
        self.seen.append(url)
        if not url.startswith(("https://", "http://")):
            raise ValueError("unsafe")
        return url


class FakeCipher:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def encrypt(self, url: str) -> EncryptedUrl:
        self.seen.append(url)
        return EncryptedUrl(b"opaque-ciphertext", b"nonce", "primary")

    def decrypt(self, envelope: EncryptedUrl) -> str:
        if envelope.key_id != "primary":
            raise ValueError("unknown key")
        return "https://example.com/video"


class FakeRunner:
    def __init__(self, inspection: RunnerInspection) -> None:
        self.inspection = inspection
        self.seen: list[str] = []

    async def resolve_access_policy(
        self, url: str, requested: ProviderAccessPolicy | None = None
    ) -> ProviderAccessPolicy:
        return requested or ProviderAccessPolicy.PUBLIC

    async def inspect(
        self, url: str, *, access_policy: ProviderAccessPolicy
    ) -> RunnerInspection:
        self.seen.append(url)
        return self.inspection


class FakeStorage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str | None, bool]] = []
        self.local_browser_signing: list[bool] = []
        self.deleted: list[str] = []
        self.aborted: list[tuple[str, str]] = []

    async def presigned_download(
        self,
        object_key: str,
        *,
        title: str | None = None,
        ttl_seconds: int,
        inline: bool = False,
        use_local_browser_endpoint: bool = False,
    ) -> str:
        self.calls.append((object_key, ttl_seconds, title, inline))
        self.local_browser_signing.append(use_local_browser_endpoint)
        return "https://objects.example/download-token"

    async def abort_multipart_upload(self, object_key: str, upload_id: str) -> None:
        self.aborted.append((object_key, upload_id))

    async def delete(self, object_key: str) -> None:
        self.deleted.append(object_key)


class FakeRepository:
    def __init__(self) -> None:
        self.inspections: dict[UUID, InspectionSnapshot] = {}
        self.jobs: dict[UUID, JobSnapshot] = {}
        self.artifacts: dict[UUID, ArtifactSnapshot] = {}
        self.inspection_commands: list[InspectionCreate] = []
        self.download_commands: list[DownloadCreate] = []
        self._inspection_keys: dict[tuple[str, str], UUID] = {}
        self._download_keys: dict[tuple[str, str], UUID] = {}
        self._download_fingerprints: dict[UUID, str] = {}
        self.outbox_events = 0
        self.thumbnails: dict[UUID, ThumbnailObject] = {}
        self.deletion_cleanup: dict[UUID, tuple[DownloadCleanupRef, ...]] = {}
        self.deletion_conflict = False

    async def save_inspection(self, command: InspectionCreate) -> InspectionSaveResult:
        self.inspection_commands.append(command)
        key = (command.owner_hash, command.idempotency_key)
        existing_id = self._inspection_keys.get(key)
        if existing_id is not None:
            existing = self.inspections[existing_id]
            if existing.request_fingerprint != command.request_fingerprint:
                raise PersistenceIdempotencyConflict
            return InspectionSaveResult(existing, created=False)
        formats = tuple(
            FormatSnapshot(
                id=item.id,
                display_name=item.display_name,
                plan_fingerprint=item.plan_fingerprint,
                semantic_plan=item.semantic_plan,
                provider_hints=item.provider_hints,
                expires_at=item.expires_at,
            )
            for item in command.formats
        )
        snapshot = InspectionSnapshot(
            id=command.id,
            owner_hash=command.owner_hash,
            request_fingerprint=command.request_fingerprint,
            extractor_key=command.extractor_key,
            provider_media_id=command.provider_media_id,
            title=command.title,
            duration_seconds=command.duration_seconds,
            metadata=command.metadata,
            thumbnail_available=False,
            expires_at=command.expires_at,
            formats=formats,
        )
        self.inspections[command.id] = snapshot
        self._inspection_keys[key] = command.id
        return InspectionSaveResult(snapshot, created=True)

    async def get_inspection(
        self, inspection_id: UUID, owner_hash: str, now: datetime
    ) -> InspectionSnapshot | None:
        del owner_hash, now
        return self.inspections.get(inspection_id)

    async def create_job(
        self, command: DownloadCreate, *, now: datetime
    ) -> JobSaveResult:
        self.download_commands.append(command)
        key = (command.owner_hash, command.idempotency_key)
        existing_id = self._download_keys.get(key)
        if existing_id is not None:
            existing = self.jobs[existing_id]
            if self._download_fingerprints[existing_id] != command.request_fingerprint:
                raise PersistenceIdempotencyConflict
            return JobSaveResult(existing, created=False)
        job = JobSnapshot.queued(command, now=now)
        self.jobs[job.id] = job
        self._download_keys[key] = job.id
        self._download_fingerprints[job.id] = command.request_fingerprint
        self.outbox_events += 1
        return JobSaveResult(job, created=True)

    async def get_job(self, job_id: UUID) -> JobSnapshot | None:
        return self.jobs.get(job_id)

    async def get_download_presentation(
        self, job_id: UUID, owner_hash: str
    ) -> DownloadPresentationSnapshot | None:
        job = self.jobs.get(job_id)
        if job is None or job.owner_hash != owner_hash:
            return None
        inspection = self.inspections.get(job.inspection_id)
        if inspection is None:
            return None
        legacy_thumbnail = inspection.metadata.get("thumbnail_url")
        return DownloadPresentationSnapshot(
            title=inspection.title,
            extractor_key=inspection.extractor_key,
            duration_seconds=inspection.duration_seconds,
            thumbnail_available=(
                job.inspection_id in self.thumbnails
                or isinstance(legacy_thumbnail, str)
            ),
        )

    async def get_thumbnail_source(
        self, inspection_id: UUID, owner_hash: str
    ) -> ThumbnailSource | None:
        inspection = self.inspections.get(inspection_id)
        if inspection is None or inspection.owner_hash != owner_hash:
            return None
        legacy = inspection.metadata.get("thumbnail_url")
        return ThumbnailSource(
            inspection_id=inspection_id,
            owner_hash=owner_hash,
            object=self.thumbnails.get(inspection_id),
            legacy_data_url=legacy if isinstance(legacy, str) else None,
        )

    async def save_thumbnail(
        self,
        inspection_id: UUID,
        owner_hash: str,
        thumbnail: ThumbnailObject,
    ) -> None:
        inspection = self.inspections.get(inspection_id)
        if inspection is None or inspection.owner_hash != owner_hash:
            return
        self.thumbnails[inspection_id] = thumbnail
        metadata = dict(inspection.metadata)
        metadata.pop("thumbnail_url", None)
        self.inspections[inspection_id] = replace(
            inspection, metadata=metadata, thumbnail_available=True
        )

    async def cancel_job(
        self, job_id: UUID, owner_hash: str, now: datetime
    ) -> JobSnapshot | None:
        job = self.jobs.get(job_id)
        if job is None or job.owner_hash != owner_hash:
            return None
        cancelled = replace(
            job,
            status="cancelled",
            stage=None,
            error_code="cancelled",
            finished_at=now,
            updated_at=now,
        )
        self.jobs[job_id] = cancelled
        return cancelled

    async def get_artifact(
        self, job_id: UUID, owner_hash: str, now: datetime
    ) -> ArtifactSnapshot | None:
        job = self.jobs.get(job_id)
        artifact = self.artifacts.get(job_id)
        if job is None or job.owner_hash != owner_hash or artifact is None:
            return None
        return artifact

    async def prepare_download_deletion(
        self, job_id: UUID, owner_hash: str, *, now: datetime
    ) -> DownloadDeletionPlan:
        del now
        job = self.jobs.get(job_id)
        if job is None or job.owner_hash != owner_hash:
            from app.services.downloads.errors import PersistenceNotFound

            raise PersistenceNotFound
        if self.deletion_conflict:
            from app.services.downloads.errors import PersistenceConflict

            raise PersistenceConflict
        return DownloadDeletionPlan(
            job_id=job_id,
            owner_hash=owner_hash,
            attempt=job.attempt,
            cleanup=self.deletion_cleanup.get(job_id, ()),
        )

    async def finish_download_deletion(self, job_id: UUID, owner_hash: str) -> None:
        if self.jobs[job_id].owner_hash != owner_hash:
            return
        self.jobs.pop(job_id)
        self.artifacts.pop(job_id, None)
