from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from app.services.downloads.errors import (
    ApplicationError,
    ApplicationErrorCode,
    MediaInspectionAuthRequired,
    MediaInspectionConfigurationMissing,
    MediaInspectionContentRestricted,
    MediaInspectionDrmProtected,
    MediaInspectionDurationLimitExceeded,
    MediaInspectionFailure,
    MediaInspectionFormatUnavailable,
    MediaInspectionGeoRestricted,
    MediaInspectionLinkUnavailable,
    MediaInspectionMediaUnsupported,
    MediaInspectionPaidContentRestricted,
    MediaInspectionPolicyNotAllowed,
    MediaInspectionRateLimited,
    MediaInspectionSessionExpired,
    MediaInspectionSessionNotReady,
    MediaInspectionTemporarilyUnavailable,
    MediaInspectionTimeout,
    MediaInspectionUnsupported,
    MediaInspectionVerificationFailed,
    PersistenceIdempotencyConflict,
)
from app.services.downloads.inspection_models import (
    FormatCreate,
    InspectionCreate,
    InspectionView,
    RunnerFormat,
    RunnerInspection,
)
from app.services.downloads.paid_content_admission import paid_content_admission
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
from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_types import ProviderAccessMode, ProviderKey


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
        *,
        access_policy: ProviderAccessPolicy | None = None,
    ) -> InspectionView:
        command = await self.prepare(
            url, owner_hash, idempotency_key, access_policy=access_policy
        )
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
        access_policy: ProviderAccessPolicy | None = None,
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
            if access_policy not in {None, ProviderAccessPolicy.PUBLIC}:
                raise ApplicationError(
                    ApplicationErrorCode.PROVIDER_ACCESS_POLICY_NOT_ALLOWED
                )
            return self._restricted_command(
                validated_url,
                owner_hash,
                idempotency_key,
                restricted,
            )
        try:
            selected_policy = await self._runner.resolve_access_policy(
                validated_url, access_policy
            )
            result = await self._runner.inspect(
                validated_url, access_policy=selected_policy
            )
        except MediaInspectionConfigurationMissing as exc:
            raise ApplicationError(
                ApplicationErrorCode.PROVIDER_CONFIGURATION_MISSING
            ) from exc
        except MediaInspectionPolicyNotAllowed as exc:
            raise ApplicationError(
                ApplicationErrorCode.PROVIDER_ACCESS_POLICY_NOT_ALLOWED
            ) from exc
        except MediaInspectionDurationLimitExceeded as exc:
            raise ApplicationError(
                ApplicationErrorCode.DURATION_LIMIT_EXCEEDED
            ) from exc
        except MediaInspectionAuthRequired as exc:
            raise ApplicationError(ApplicationErrorCode.PROVIDER_AUTH_REQUIRED) from exc
        except MediaInspectionSessionExpired as exc:
            raise ApplicationError(
                ApplicationErrorCode.PROVIDER_SESSION_EXPIRED
            ) from exc
        except MediaInspectionSessionNotReady as exc:
            raise ApplicationError(
                ApplicationErrorCode.PROVIDER_SESSION_NOT_READY,
                preparation_wait=exc.before_media_io,
            ) from exc
        except MediaInspectionVerificationFailed as exc:
            raise ApplicationError(
                ApplicationErrorCode.PROVIDER_VERIFICATION_FAILED
            ) from exc
        except MediaInspectionRateLimited as exc:
            raise ApplicationError(
                ApplicationErrorCode.PROVIDER_RATE_LIMITED, retry_at=exc.retry_at
            ) from exc
        except MediaInspectionGeoRestricted as exc:
            raise ApplicationError(
                ApplicationErrorCode.PROVIDER_GEO_RESTRICTED
            ) from exc
        except MediaInspectionPaidContentRestricted as exc:
            return self._restricted_command(
                validated_url,
                owner_hash,
                idempotency_key,
                paid_content_admission(validated_url, exc.reason),
                access_policy=selected_policy,
            )
        except MediaInspectionContentRestricted as exc:
            raise ApplicationError(
                ApplicationErrorCode.PROVIDER_CONTENT_RESTRICTED
            ) from exc
        except MediaInspectionDrmProtected as exc:
            raise ApplicationError(ApplicationErrorCode.PROVIDER_DRM_PROTECTED) from exc
        except MediaInspectionTemporarilyUnavailable as exc:
            raise ApplicationError(
                ApplicationErrorCode.PROVIDER_TEMPORARILY_UNAVAILABLE
            ) from exc
        except MediaInspectionLinkUnavailable as exc:
            raise ApplicationError(
                ApplicationErrorCode.PROVIDER_LINK_UNAVAILABLE
            ) from exc
        except MediaInspectionMediaUnsupported as exc:
            raise ApplicationError(
                ApplicationErrorCode.PROVIDER_MEDIA_UNSUPPORTED
            ) from exc
        except MediaInspectionFormatUnavailable as exc:
            raise ApplicationError(ApplicationErrorCode.FORMAT_UNAVAILABLE) from exc
        except MediaInspectionUnsupported as exc:
            raise ApplicationError(ApplicationErrorCode.PROVIDER_UNSUPPORTED) from exc
        except MediaInspectionTimeout as exc:
            raise ApplicationError(ApplicationErrorCode.INSPECTION_TIMEOUT) from exc
        except MediaInspectionFailure as exc:
            raise ApplicationError(ApplicationErrorCode.INSPECTION_FAILED) from exc
        if result.media_kind is MediaKind.VIDEO and result.duration_seconds <= 0:
            raise ApplicationError(ApplicationErrorCode.INSPECTION_FAILED)
        if (
            result.media_kind in {MediaKind.IMAGE_GALLERY, MediaKind.VIDEO_COLLECTION}
            and result.asset_count <= 0
        ):
            raise ApplicationError(ApplicationErrorCode.INSPECTION_FAILED)
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
                "inspection", validated_url, selected_policy.value
            ),
            url_ciphertext=envelope.ciphertext,
            url_nonce=envelope.nonce,
            url_key_id=envelope.key_id,
            extractor_key=_required(result.extractor_key),
            provider_media_id=_required(result.provider_media_id),
            title=_required(result.title),
            duration_seconds=result.duration_seconds,
            metadata={
                **_inspection_metadata(result),
                "access_policy_id": selected_policy.value,
            },
            expires_at=expires_at,
            formats=formats,
        )
        return command

    def _restricted_command(
        self,
        validated_url: str,
        owner_hash: str,
        idempotency_key: str,
        restricted: RestrictedSourceAdmission,
        *,
        access_policy: ProviderAccessPolicy = ProviderAccessPolicy.PUBLIC,
    ) -> InspectionCreate:
        now = validate_now(self._now())
        envelope = self._url_cipher.encrypt(validated_url)
        command = InspectionCreate(
            id=self._new_id(),
            owner_hash=owner_hash,
            idempotency_key=idempotency_key,
            request_fingerprint=self._fingerprinter.fingerprint(
                "inspection", validated_url, access_policy.value
            ),
            url_ciphertext=envelope.ciphertext,
            url_nonce=envelope.nonce,
            url_key_id=envelope.key_id,
            extractor_key=restricted.provider_key,
            provider_media_id=restricted.provider_media_id,
            title=restricted.title,
            duration_seconds=0,
            metadata={**restricted.metadata(), "access_policy_id": access_policy.value},
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
        raise ApplicationError(ApplicationErrorCode.INSPECTION_FAILED)
    return value


def _inspection_metadata(result: RunnerInspection) -> dict[str, object]:
    metadata: dict[str, object] = {
        "provider_access_context": result.access_context.to_document()
    }
    if (
        result.access_context.provider_key in {ProviderKey.YOUKU, ProviderKey.QQVIDEO}
        and result.access_context.access_mode is ProviderAccessMode.OPERATOR_MANAGED
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
