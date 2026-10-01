from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from app.services.provider_failures import ProviderFailure


class ApplicationErrorCode(StrEnum):
    ARTICLE_ACCESS_RESTRICTED = "article_access_restricted"
    ARTICLE_DISCOVERY_FAILED = "article_discovery_failed"
    DOWNLOAD_NOT_READY = "download_not_ready"
    DURATION_LIMIT_EXCEEDED = "duration_limit_exceeded"
    FORMAT_UNAVAILABLE = "format_unavailable"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    INTERNAL_ERROR = "internal_error"
    INVALID_REQUEST = "invalid_request"
    INVALID_STATE = "invalid_state"
    INVALID_URL = "invalid_url"
    NOT_FOUND = "not_found"
    NETWORK_BLOCKED = "network_blocked"
    CHALLENGE = "challenge"
    LOGIN_REQUIRED = "login_required"
    IDENTITY_UNAVAILABLE = "identity_unavailable"
    RATE_LIMITED = "rate_limited"
    CONTEXT_CHANGED = "context_changed"
    CONTENT_UNAVAILABLE = "content_unavailable"
    CONTENT_PROTECTED = "content_protected"
    EXTRACTOR_BROKEN = "extractor_broken"
    TRANSIENT = "transient"
    INVALID_INPUT = "invalid_input"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    RESOURCE_EXPIRED = "resource_expired"
    STORAGE_UNAVAILABLE = "storage_unavailable"


class ApplicationError(RuntimeError):
    def __init__(
        self,
        code: ApplicationErrorCode,
        *,
        retry_at: datetime | None = None,
        failure: ProviderFailure | None = None,
    ) -> None:
        self.code = code
        self.retry_at = retry_at
        self.failure = failure
        super().__init__(code.value)


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
        failure: ProviderFailure | None = None,
    ) -> None:
        self.failure = failure
        super().__init__(*args)
