from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from app.services.downloads.errors import (
    ApplicationError,
    ApplicationErrorCode,
    MediaInspectionFailure,
    PersistenceIdempotencyConflict,
)
from app.services.downloads.inspection_models import (
    FormatCreate,
    InspectionCreate,
    InspectionView,
    RunnerFormat,
    RunnerInspection,
)
from app.services.downloads.plans import plan_fingerprint, plan_to_documents
from app.services.downloads.ports import (
    DownloadRepository,
    MediaRunner,
    RequestFingerprinter,
    UrlCipher,
    UrlValidator,
)
from app.services.downloads.rules.enums import MediaKind
from app.services.downloads.source_admission import (
    RestrictedSourceAdmission,
    classify_restricted_source,
)
from app.services.downloads.thumbnail import ThumbnailStorageError
from app.services.downloads.thumbnail_use_cases import PersistThumbnail
from app.services.downloads.validation import (
    validate_idempotency_key,
    validate_now,
    validate_owner_hash,
)
from app.services.downloads.views import inspection_view
from app.services.provider_failures import ProviderFailure
from app.services.provider_types import ProviderKey


class InspectMedia:
    def __init__(
        self,
        *,
        repository: DownloadRepository,
        runner: MediaRunner,
        url_validator: UrlValidator,
        url_cipher: UrlCipher,
        fingerprinter: RequestFingerprinter,
        now: Callable[[], datetime],
        new_id: Callable[[], UUID],
        inspection_ttl: timedelta,
        max_duration_seconds: int,
        persist_thumbnail: PersistThumbnail | None = None,
    ) -> None:
        if inspection_ttl <= timedelta(0) or max_duration_seconds <= 0:
            raise ValueError("inspection limits must be positive")
        self._repository = repository
        self._runner = runner
        self._url_validator = url_validator
        self._url_cipher = url_cipher
        self._fingerprinter = fingerprinter
        self._now = now
        self._new_id = new_id
        self._ttl = inspection_ttl
        self._max_duration = max_duration_seconds
        self._persist_thumbnail = persist_thumbnail

    async def __call__(
        self,
        url: str,
        owner_hash: str,
        idempotency_key: str,
    ) -> InspectionView:
        command = await self.prepare(url, owner_hash, idempotency_key)
        try:
            saved = await self._repository.save_inspection(command)
        except PersistenceIdempotencyConflict as exc:
            raise ApplicationError(ApplicationErrorCode.IDEMPOTENCY_CONFLICT) from exc
        thumbnail = command.metadata.get("thumbnail_url")
        if self._persist_thumbnail is not None and isinstance(thumbnail, str):
            try:
                await self._persist_thumbnail(
                    saved.inspection.id, owner_hash, thumbnail
                )
            except (ThumbnailStorageError, ValueError):
                pass
        return inspection_view(saved.inspection)

    async def prepare(
        self,
        url: str,
        owner_hash: str,
        idempotency_key: str,
        *,
        task_id: str | None = None,
        deadline: datetime | None = None,
    ) -> InspectionCreate:
        """Compute a result without persistence; the caller owns its commit."""
        owner_hash = validate_owner_hash(owner_hash)
        idempotency_key = validate_idempotency_key(idempotency_key)
        try:
            validated_url = self._url_validator.validate(url)
        except ValueError as exc:
            raise ApplicationError(ApplicationErrorCode.INVALID_URL) from exc
        restricted = classify_restricted_source(validated_url)
        if restricted is not None:
            return self._restricted_command(
                validated_url,
                owner_hash,
                idempotency_key,
                restricted,
            )
        try:
            result = await self._runner.inspect(
                validated_url, task_id=task_id, deadline=deadline
            )
        except MediaInspectionFailure as exc:
            failure = exc.failure or ProviderFailure.for_code("extractor_broken")
            raise ApplicationError(
                ApplicationErrorCode(failure.failure_class.value),
                retry_at=failure.retry_after,
                failure=failure,
            ) from exc
        if result.media_kind is MediaKind.VIDEO and result.duration_seconds <= 0:
            raise ApplicationError(ApplicationErrorCode.EXTRACTOR_BROKEN)
        if (
            result.media_kind in {MediaKind.IMAGE_GALLERY, MediaKind.VIDEO_COLLECTION}
            and result.asset_count <= 0
        ):
            raise ApplicationError(ApplicationErrorCode.EXTRACTOR_BROKEN)
        if (
            result.media_kind is MediaKind.VIDEO
            and result.duration_seconds > self._max_duration
        ):
            raise ApplicationError(ApplicationErrorCode.DURATION_LIMIT_EXCEEDED)

        now = validate_now(self._now())
        expires_at = now + self._ttl
        formats = self._formats(
            result.formats,
            expires_at,
            media_kind=result.media_kind,
            asset_count=result.asset_count,
        )
        if not formats:
            raise ApplicationError(ApplicationErrorCode.FORMAT_UNAVAILABLE)
        envelope = self._url_cipher.encrypt(validated_url)
        command = InspectionCreate(
            id=self._new_id(),
            owner_hash=owner_hash,
            idempotency_key=idempotency_key,
            request_fingerprint=self._fingerprinter.fingerprint(
                "inspection", validated_url
            ),
            url_ciphertext=envelope.ciphertext,
            url_nonce=envelope.nonce,
            url_key_id=envelope.key_id,
            extractor_key=_required(result.extractor_key),
            provider_media_id=_required(result.provider_media_id),
            title=_required(result.title),
            duration_seconds=result.duration_seconds,
            metadata=_inspection_metadata(result),
            expires_at=expires_at,
            formats=formats,
        )
        return command

    async def cancel(self, task_id: str) -> None:
        """Return only after the Runner confirms its resource cleanup."""
        await self._runner.cancel(task_id)

    def _restricted_command(
        self,
        validated_url: str,
        owner_hash: str,
        idempotency_key: str,
        restricted: RestrictedSourceAdmission,
    ) -> InspectionCreate:
        now = validate_now(self._now())
        envelope = self._url_cipher.encrypt(validated_url)
        command = InspectionCreate(
            id=self._new_id(),
            owner_hash=owner_hash,
            idempotency_key=idempotency_key,
            request_fingerprint=self._fingerprinter.fingerprint(
                "inspection", validated_url
            ),
            url_ciphertext=envelope.ciphertext,
            url_nonce=envelope.nonce,
            url_key_id=envelope.key_id,
            extractor_key=restricted.provider_key,
            provider_media_id=restricted.provider_media_id,
            title=restricted.title,
            duration_seconds=0,
            metadata=restricted.metadata(),
            expires_at=now + self._ttl,
            formats=(),
        )
        return command

    def _formats(
        self,
        formats: tuple[RunnerFormat, ...],
        expires_at: datetime,
        *,
        media_kind: MediaKind,
        asset_count: int,
    ) -> tuple[FormatCreate, ...]:
        if media_kind in {MediaKind.IMAGE_GALLERY, MediaKind.VIDEO_COLLECTION}:
            semantic: dict[str, object] = {
                "media_kind": media_kind.value,
                "asset_count": asset_count,
            }
            return (
                FormatCreate(
                    id=self._new_id(),
                    display_name=(
                        f"{asset_count} 张原图（ZIP）"
                        if media_kind is MediaKind.IMAGE_GALLERY
                        else f"{asset_count} 个视频（ZIP）"
                    ),
                    plan_fingerprint=plan_fingerprint(semantic),
                    semantic_plan=semantic,
                    provider_hints={},
                    expires_at=expires_at,
                ),
            )
        unique: dict[str, FormatCreate] = {}
        for item in formats:
            if item.plan is None:
                continue
            semantic, hints = plan_to_documents(item.plan)
            fingerprint = plan_fingerprint(semantic)
            unique.setdefault(
                fingerprint,
                FormatCreate(
                    id=self._new_id(),
                    display_name=_required(item.display_name),
                    plan_fingerprint=fingerprint,
                    semantic_plan=semantic,
                    provider_hints=hints,
                    expires_at=expires_at,
                ),
            )
        return tuple(unique.values())


def _required(value: str) -> str:
    value = value.strip()
    if not value:
        raise ApplicationError(ApplicationErrorCode.EXTRACTOR_BROKEN)
    return value


def _inspection_metadata(result: RunnerInspection) -> dict[str, object]:
    metadata: dict[str, object] = {
        "execution_context": result.execution_context.to_document()
    }
    if (
        result.execution_context.provider_key
        in {ProviderKey.YOUKU, ProviderKey.QQVIDEO}
        and result.execution_context.identity_used
    ):
        # A complete account-visible stream is not an official export grant.
        metadata["entitlement_state"] = "unknown"
        metadata["rights_basis"] = None
    if result.media_kind in {MediaKind.IMAGE_GALLERY, MediaKind.VIDEO_COLLECTION}:
        metadata["media_kind"] = result.media_kind.value
        metadata["asset_count"] = result.asset_count
    if result.thumbnail_data_url is not None:
        metadata["thumbnail_url"] = result.thumbnail_data_url
    return metadata
