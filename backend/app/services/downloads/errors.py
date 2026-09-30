from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from app.services.downloads.rules.content_restrictions import ContentRestriction
from app.services.provider_failures import ProviderFailure
from app.services.provider_types import ProviderAccessMode


class ApplicationErrorCode(StrEnum):
    ARTICLE_ACCESS_RESTRICTED = "article_access_restricted"
    ARTICLE_DISCOVERY_FAILED = "article_discovery_failed"
    DOWNLOAD_NOT_READY = "download_not_ready"
    DURATION_LIMIT_EXCEEDED = "duration_limit_exceeded"
    FORMAT_UNAVAILABLE = "format_unavailable"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    INSPECTION_FAILED = "inspection_failed"
    INSPECTION_TIMEOUT = "inspection_timeout"
    INTERNAL_ERROR = "internal_error"
    INVALID_REQUEST = "invalid_request"
    INVALID_STATE = "invalid_state"
    INVALID_URL = "invalid_url"
    NOT_FOUND = "not_found"
    PROVIDER_AUTH_REQUIRED = "provider_auth_required"
    PROVIDER_CONFIGURATION_MISSING = "provider_configuration_missing"
    PROVIDER_GUEST_CONTEXT_REQUIRED = "provider_guest_context_required"
    PROVIDER_ACCESS_POLICY_NOT_ALLOWED = "provider_access_policy_not_allowed"
    PROVIDER_SESSION_EXPIRED = "provider_session_expired"
    PROVIDER_SESSION_NOT_READY = "provider_session_not_ready"
    PROVIDER_VERIFICATION_FAILED = "provider_verification_failed"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    PROVIDER_GEO_RESTRICTED = "provider_geo_restricted"
    PROVIDER_CONTENT_RESTRICTED = "provider_content_restricted"
    PROVIDER_DRM_PROTECTED = "provider_drm_protected"
    PROVIDER_TEMPORARILY_UNAVAILABLE = "provider_temporarily_unavailable"
    PROVIDER_LINK_UNAVAILABLE = "provider_link_unavailable"
    PROVIDER_MEDIA_UNSUPPORTED = "provider_media_unsupported"
    PROVIDER_UNSUPPORTED = "provider_unsupported"
    RESOURCE_EXPIRED = "resource_expired"
    STORAGE_UNAVAILABLE = "storage_unavailable"


class ApplicationError(RuntimeError):
    def __init__(
        self,
        code: ApplicationErrorCode,
        *,
        retry_at: datetime | None = None,
        preparation_wait: bool = False,
        failure: ProviderFailure | None = None,
    ) -> None:
        self.code = code
        self.retry_at = retry_at
        self.preparation_wait = preparation_wait
        self.failure = failure
        super().__init__(code.value)

    @classmethod
    def from_inspection(
        cls,
        code: ApplicationErrorCode,
        error: MediaInspectionFailure,
        *,
        preparation_wait: bool = False,
    ) -> Self:
        return cls(
            code,
            failure=error.failure,
            retry_at=getattr(error, "retry_at", None),
            preparation_wait=preparation_wait,
        )


class PersistenceIdempotencyConflict(RuntimeError):
    """A persistence adapter observed an idempotency fingerprint mismatch."""


class PersistenceNotFound(RuntimeError):
    """A persistence adapter could not find an aggregate."""


class PersistenceConflict(RuntimeError):
    """A persistence adapter lost an atomic state precondition race."""


class MediaInspectionFailure(RuntimeError):
    """The runner could not return a valid inspection."""

    def __init__(
        self,
        *args: object,
        access_mode: ProviderAccessMode | None = None,
        failure: ProviderFailure | None = None,
    ) -> None:
        self.access_mode = access_mode
        self.failure = failure
        super().__init__(*args)

    def attributed_to(self, access_mode: ProviderAccessMode) -> Self:
        """Attach the concrete attempt without changing the public error type."""
        self.access_mode = access_mode
        return self

    def with_failure(self, failure: ProviderFailure) -> Self:
        self.failure = failure
        return self


class MediaInspectionDurationLimitExceeded(MediaInspectionFailure):
    """The media exceeds the configured duration safety boundary."""


class MediaInspectionAuthRequired(MediaInspectionFailure):
    """The provider requires an approved session."""


class MediaInspectionConfigurationMissing(MediaInspectionFailure):
    """The selected approved route has no configured runner endpoint."""


class MediaInspectionPolicyNotAllowed(MediaInspectionFailure):
    """The requested policy is not admitted for this provider."""


class MediaInspectionSessionExpired(MediaInspectionFailure):
    """The selected provider session is no longer usable."""


class MediaInspectionSessionNotReady(MediaInspectionFailure):
    """The site has a deployment session, but it is not ready; never anonymous."""

    def __init__(self, *, before_media_io: bool = False) -> None:
        self.before_media_io = before_media_io
        super().__init__()


class MediaInspectionVerificationFailed(MediaInspectionFailure):
    """Provider request proof, script challenge, or egress verification failed."""


class MediaInspectionRateLimited(MediaInspectionFailure):
    """The provider rejected the bounded request rate."""

    def __init__(self, *, retry_at: datetime | None = None) -> None:
        self.retry_at = retry_at
        super().__init__()


class MediaInspectionGeoRestricted(MediaInspectionFailure):
    """The content is unavailable in the configured region."""


class MediaInspectionContentRestricted(MediaInspectionFailure):
    """The content is private or requires an entitlement."""


class MediaInspectionPaidContentRestricted(MediaInspectionContentRestricted):
    """Original platform metadata identified a paid or incomplete source."""

    def __init__(self, reason: ContentRestriction) -> None:
        self.reason = reason
        super().__init__(reason.value)


class MediaInspectionDrmProtected(MediaInspectionFailure):
    """The content is DRM protected and outside the product boundary."""


class MediaInspectionTemporarilyUnavailable(MediaInspectionFailure):
    """The provider adapter or attestation service is degraded."""


class MediaInspectionLinkUnavailable(MediaInspectionFailure):
    """The submitted provider link no longer resolves to playable media."""


class MediaInspectionMediaUnsupported(MediaInspectionFailure):
    """The submitted provider item is not a supported single video."""


class MediaInspectionFormatUnavailable(MediaInspectionFailure):
    """The media resolved but offers no supported semantic download format."""


class MediaInspectionUnsupported(MediaInspectionFailure):
    """The provider is outside the capabilities of the secure runner."""


class MediaInspectionTimeout(MediaInspectionFailure):
    """The runner exceeded the bounded inspection deadline."""
