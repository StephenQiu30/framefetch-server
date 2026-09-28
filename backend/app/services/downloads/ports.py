from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.services.downloads.analytics_models import DownloadAnalyticsSnapshot
from app.services.downloads.download_models import (
    ArtifactSnapshot,
    DownloadCreate,
    DownloadDeletionPlan,
    DownloadPresentationSnapshot,
    JobSaveResult,
    JobSnapshot,
)
from app.services.downloads.history_models import DownloadHistoryPageSnapshot
from app.services.downloads.inspection_models import (
    EncryptedUrl,
    InspectionCreate,
    InspectionSaveResult,
    InspectionSnapshot,
    RunnerInspection,
)
from app.services.downloads.thumbnail import (
    DownloadThumbnailSource,
    ThumbnailObject,
    ThumbnailSource,
)
from app.services.provider_access import ProviderAccessPolicy


class UrlValidator(Protocol):
    def validate(self, url: str) -> str: ...


class UrlCipher(Protocol):
    def encrypt(self, url: str) -> EncryptedUrl: ...

    def decrypt(self, envelope: EncryptedUrl) -> str: ...


class MediaRunner(Protocol):
    async def resolve_access_policy(
        self, url: str, requested: ProviderAccessPolicy | None = None
    ) -> ProviderAccessPolicy: ...

    async def inspect(
        self, url: str, *, access_policy: ProviderAccessPolicy
    ) -> RunnerInspection: ...


class RequestFingerprinter(Protocol):
    def fingerprint(self, namespace: str, *values: str) -> str: ...


class DownloadRepository(Protocol):
    async def save_inspection(
        self, command: InspectionCreate
    ) -> InspectionSaveResult: ...

    async def get_inspection(
        self, inspection_id: UUID, owner_hash: str, now: datetime
    ) -> InspectionSnapshot | None: ...

    async def create_job(
        self, command: DownloadCreate, *, now: datetime
    ) -> JobSaveResult: ...

    async def get_job(self, job_id: UUID) -> JobSnapshot | None: ...

    async def get_download_presentation(
        self, job_id: UUID, owner_hash: str
    ) -> DownloadPresentationSnapshot | None: ...

    async def get_thumbnail_source(
        self, inspection_id: UUID, owner_hash: str
    ) -> ThumbnailSource | None: ...

    async def save_thumbnail(
        self,
        inspection_id: UUID,
        owner_hash: str,
        thumbnail: ThumbnailObject,
    ) -> None: ...

    async def get_download_thumbnail_source(
        self, job_id: UUID, owner_hash: str
    ) -> DownloadThumbnailSource | None: ...

    async def save_download_thumbnail(
        self,
        job_id: UUID,
        owner_hash: str,
        thumbnail: ThumbnailObject,
    ) -> None: ...

    async def list_download_history(
        self,
        owner_hash: str,
        *,
        page: int,
        page_size: int,
        status: str | None,
        search: str | None,
        now: datetime,
    ) -> DownloadHistoryPageSnapshot: ...

    async def get_download_analytics(
        self,
        *,
        start: datetime,
        end: datetime,
    ) -> DownloadAnalyticsSnapshot: ...

    async def cancel_job(
        self, job_id: UUID, owner_hash: str, now: datetime
    ) -> JobSnapshot | None: ...

    async def get_artifact(
        self, job_id: UUID, owner_hash: str, now: datetime
    ) -> ArtifactSnapshot | None: ...

    async def prepare_download_deletion(
        self, job_id: UUID, owner_hash: str, *, now: datetime
    ) -> DownloadDeletionPlan: ...

    async def finish_download_deletion(self, job_id: UUID, owner_hash: str) -> None: ...


class ObjectStorage(Protocol):
    async def presigned_download(
        self,
        object_key: str,
        *,
        title: str | None = None,
        ttl_seconds: int,
        inline: bool = False,
        use_local_browser_endpoint: bool = False,
    ) -> str: ...


class DownloadArtifactStorage(Protocol):
    """Read completed artifacts without exposing a storage endpoint."""

    def iter_download(
        self,
        object_key: str,
        *,
        offset: int,
        length: int,
        chunk_size: int = 1024 * 1024,
    ) -> Iterator[bytes]: ...


class DownloadDeletionStorage(Protocol):
    async def abort_multipart_upload(self, object_key: str, upload_id: str) -> None: ...

    async def delete(self, object_key: str) -> None: ...


class ThumbnailObjectStorage(Protocol):
    async def store(self, inspection_id: UUID, data_url: str) -> ThumbnailObject: ...

    async def read(self, thumbnail: ThumbnailObject) -> bytes: ...
