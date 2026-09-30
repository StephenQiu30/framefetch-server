"""Failure facts shared by provider execution and business rules; no I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Self

_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


class FailurePhase(StrEnum):
    RECOGNIZE = "recognize"
    PREPARE_CONTEXT = "prepare_context"
    FETCH_METADATA = "fetch_metadata"
    SELECT_FORMAT = "select_format"
    PROBE_MEDIA = "probe_media"
    TRANSFER = "transfer"
    VALIDATE = "validate"
    PUBLISH = "publish"


class FailureScope(StrEnum):
    CONTENT = "content"
    SESSION = "session"
    ROUTE = "route"
    DEPENDENCY = "dependency"
    RUNTIME = "runtime"


class FailureClass(StrEnum):
    AUTH_REQUIRED = "auth_required"
    SESSION_EXPIRED = "session_expired"
    CHALLENGE_REQUIRED = "challenge_required"
    TOKEN_UNAVAILABLE = "token_unavailable"
    TOKEN_REJECTED = "token_rejected"
    EXTRACTOR_CHANGED = "extractor_changed"
    PROTOCOL_UNAVAILABLE = "protocol_unavailable"
    FORMAT_UNAVAILABLE = "format_unavailable"
    MEDIA_PROBE_FAILED = "media_probe_failed"
    EGRESS_DENIED = "egress_denied"
    NETWORK_TRANSIENT = "network_transient"
    RATE_LIMITED = "rate_limited"
    CONTENT_UNAVAILABLE = "content_unavailable"
    CONTENT_RESTRICTED = "content_restricted"
    CONTEXT_CHANGED = "context_changed"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    CAPACITY_EXHAUSTED = "capacity_exhausted"
    INVALID_INPUT = "invalid_input"
    SOURCE_UNSUPPORTED = "source_unsupported"
    ARTIFACT_INVALID = "artifact_invalid"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    OUTCOME_UNKNOWN = "outcome_unknown"
    UPSTREAM_UNCLASSIFIED = "upstream_unclassified"


class FailureEvidenceKind(StrEnum):
    UPSTREAM_RESPONSE = "upstream_response"
    TRANSPORT = "transport"
    LOCAL_VALIDATION = "local_validation"
    RUNTIME = "runtime"
    UNKNOWN = "unknown"


# Defaults describe stable codes, not platform text. Execution supplies the
# actual phase and evidence. Unknown text never proves an authentication fault.
_DEFINITIONS: dict[str, tuple[FailureClass, FailureScope, FailurePhase]] = {}


def _define(
    codes: tuple[str, ...],
    kind: FailureClass,
    scope: FailureScope,
    phase: FailurePhase = FailurePhase.FETCH_METADATA,
) -> None:
    for code in codes:
        if code in _DEFINITIONS:
            raise ValueError(f"duplicate failure code: {code}")
        _DEFINITIONS[code] = kind, scope, phase


_define(
    ("credential_required", "provider_auth_required"),
    FailureClass.AUTH_REQUIRED,
    FailureScope.SESSION,
)
_define(
    ("credential_expired", "credential_rejected", "provider_session_expired"),
    FailureClass.SESSION_EXPIRED,
    FailureScope.SESSION,
)
_define(
    ("egress_challenged", "challenge_required", "provider_verification_failed"),
    FailureClass.CHALLENGE_REQUIRED,
    FailureScope.ROUTE,
)
_define(
    ("pot_provider_unavailable", "pot_provider_release_mismatch", "pot_required"),
    FailureClass.TOKEN_UNAVAILABLE,
    FailureScope.DEPENDENCY,
    FailurePhase.PREPARE_CONTEXT,
)
_define(("pot_rejected",), FailureClass.TOKEN_REJECTED, FailureScope.DEPENDENCY)
_define(
    ("extractor_regression",), FailureClass.EXTRACTOR_CHANGED, FailureScope.DEPENDENCY
)
_define(
    ("protocol_unavailable",),
    FailureClass.PROTOCOL_UNAVAILABLE,
    FailureScope.DEPENDENCY,
    FailurePhase.SELECT_FORMAT,
)
_define(
    ("format_unavailable", "transcode_required", "format_limit_exceeded"),
    FailureClass.FORMAT_UNAVAILABLE,
    FailureScope.CONTENT,
    FailurePhase.SELECT_FORMAT,
)
_define(
    ("media_probe_failed",),
    FailureClass.MEDIA_PROBE_FAILED,
    FailureScope.CONTENT,
    FailurePhase.PROBE_MEDIA,
)
_define(("egress_denied",), FailureClass.EGRESS_DENIED, FailureScope.ROUTE)
_define(("network_transient",), FailureClass.NETWORK_TRANSIENT, FailureScope.ROUTE)
_define(("provider_rate_limited",), FailureClass.RATE_LIMITED, FailureScope.ROUTE)
_define(
    ("provider_link_unavailable", "content_unavailable", "content_deleted"),
    FailureClass.CONTENT_UNAVAILABLE,
    FailureScope.CONTENT,
)
_define(
    (
        "content_private",
        "content_not_entitled",
        "content_entitlement_unknown",
        "content_access_metadata_invalid",
        "content_preview_only",
        "content_supporter_only",
        "content_paid_only",
        "content_export_required",
        "drm_protected",
        "provider_geo_restricted",
        "duration_limit_exceeded",
        "credential_entitlement_drift",
        "provider_content_restricted",
    ),
    FailureClass.CONTENT_RESTRICTED,
    FailureScope.CONTENT,
)
_define(
    ("credential_revoked",),
    FailureClass.CONTEXT_CHANGED,
    FailureScope.SESSION,
    FailurePhase.PREPARE_CONTEXT,
)
_define(
    ("client_context_mismatch", "context_changed"),
    FailureClass.CONTEXT_CHANGED,
    FailureScope.ROUTE,
    FailurePhase.PREPARE_CONTEXT,
)
_define(
    ("source_changed",),
    FailureClass.CONTEXT_CHANGED,
    FailureScope.CONTENT,
    FailurePhase.VALIDATE,
)
_define(
    ("runner_release_changed", "runner_release_mismatch"),
    FailureClass.CONTEXT_CHANGED,
    FailureScope.DEPENDENCY,
    FailurePhase.PREPARE_CONTEXT,
)
_define(
    (
        "runner_unavailable",
        "runner_dependency_unavailable",
        "engine_unavailable",
        "engine_catalog_unavailable",
        "runner_restarted",
        "internal_error",
    ),
    FailureClass.RUNTIME_UNAVAILABLE,
    FailureScope.RUNTIME,
    FailurePhase.PREPARE_CONTEXT,
)
_define(
    (
        "provider_session_not_ready",
        "provider_session_unavailable",
        "credential_access_denied",
        "source_read_timeout",
        "source_read_failed",
        "chrome_profile_unavailable",
    ),
    FailureClass.RUNTIME_UNAVAILABLE,
    FailureScope.SESSION,
    FailurePhase.PREPARE_CONTEXT,
)
_define(
    ("runner_busy", "workspace_limit_exceeded", "task_already_active"),
    FailureClass.CAPACITY_EXHAUSTED,
    FailureScope.RUNTIME,
    FailurePhase.PREPARE_CONTEXT,
)
_define(
    (
        "invalid_url",
        "invalid_request",
        "provider_session_not_allowed",
        "request_too_large",
        "task_not_found",
    ),
    FailureClass.INVALID_INPUT,
    FailureScope.CONTENT,
    FailurePhase.RECOGNIZE,
)
_define(
    (
        "authentication_required",
        "invalid_signature",
        "signature_expired",
        "request_replayed",
    ),
    FailureClass.INVALID_INPUT,
    FailureScope.RUNTIME,
    FailurePhase.RECOGNIZE,
)
_define(
    ("invalid_runner_response",),
    FailureClass.RUNTIME_UNAVAILABLE,
    FailureScope.RUNTIME,
    FailurePhase.VALIDATE,
)
_define(
    ("provider_unsupported", "provider_media_unsupported", "unsupported_source"),
    FailureClass.SOURCE_UNSUPPORTED,
    FailureScope.CONTENT,
    FailurePhase.RECOGNIZE,
)
_define(
    ("invalid_artifact", "remux_failed"),
    FailureClass.ARTIFACT_INVALID,
    FailureScope.CONTENT,
    FailurePhase.VALIDATE,
)
_define(
    ("storage_unavailable", "publish_failed"),
    FailureClass.STORAGE_UNAVAILABLE,
    FailureScope.DEPENDENCY,
    FailurePhase.PUBLISH,
)
_define(
    ("download_failed", "download_timeout"),
    FailureClass.OUTCOME_UNKNOWN,
    FailureScope.ROUTE,
    FailurePhase.TRANSFER,
)
_define(
    ("inspection_timeout", "cancelled", "cancellation_pending"),
    FailureClass.OUTCOME_UNKNOWN,
    FailureScope.RUNTIME,
)
_define(("outcome_unknown",), FailureClass.OUTCOME_UNKNOWN, FailureScope.RUNTIME)
_define(
    ("browser_unavailable", "browser_release_changed"),
    FailureClass.RUNTIME_UNAVAILABLE,
    FailureScope.RUNTIME,
    FailurePhase.PREPARE_CONTEXT,
)
_define(
    ("browser_capacity_exhausted", "browser_profile_limit"),
    FailureClass.CAPACITY_EXHAUSTED,
    FailureScope.RUNTIME,
    FailurePhase.PREPARE_CONTEXT,
)


def failure_definition(code: str) -> tuple[FailureClass, FailureScope, FailurePhase]:
    return _DEFINITIONS.get(
        code,
        (
            FailureClass.UPSTREAM_UNCLASSIFIED,
            FailureScope.DEPENDENCY,
            FailurePhase.FETCH_METADATA,
        ),
    )


def parse_retry_after(value: str | None, observed_at: datetime) -> datetime | None:
    if observed_at.tzinfo is None:
        raise ValueError("Retry-After observation must be timezone aware")
    if value is None or len(value) > 128:
        return None
    try:
        if value.isascii() and value.isdigit():
            return observed_at + timedelta(seconds=int(value))
        result = parsedate_to_datetime(value)
        return result if result.tzinfo is not None and result > observed_at else None
    except (ValueError, TypeError, OverflowError):
        return None


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    code: str
    phase: FailurePhase
    scope: FailureScope
    failure_class: FailureClass
    evidence_kind: FailureEvidenceKind
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    strategy_id: str | None = None
    context_key: str | None = None
    retry_after: datetime | None = None
    diagnostic_ref: str | None = None
    cause_code: str | None = None

    def __post_init__(self) -> None:
        kind, _, _ = failure_definition(self.code)
        if self.failure_class is not kind:
            raise ValueError("provider failure class does not match its code")
        if (
            kind in {FailureClass.TOKEN_UNAVAILABLE, FailureClass.TOKEN_REJECTED}
            and self.scope is not FailureScope.DEPENDENCY
        ):
            raise ValueError("provider token failure must retain dependency scope")
        if _CODE.fullmatch(self.code) is None or (
            self.cause_code is not None and _CODE.fullmatch(self.cause_code) is None
        ):
            raise ValueError("provider failure code is invalid")
        if any(
            value is not None and _REFERENCE.fullmatch(value) is None
            for value in (self.strategy_id, self.context_key, self.diagnostic_ref)
        ):
            raise ValueError("provider failure reference is invalid")
        if self.observed_at.tzinfo is None or (
            self.retry_after is not None and self.retry_after.tzinfo is None
        ):
            raise ValueError("provider failure timestamp must be timezone aware")

    @classmethod
    def for_code(
        cls,
        code: str,
        *,
        phase: FailurePhase | None = None,
        scope: FailureScope | None = None,
        evidence_kind: FailureEvidenceKind = FailureEvidenceKind.UNKNOWN,
        retry_after: datetime | None = None,
        cause_code: str | None = None,
    ) -> Self:
        kind, default_scope, default_phase = failure_definition(code)
        return cls(
            code,
            phase or default_phase,
            scope or default_scope,
            kind,
            evidence_kind,
            retry_after=retry_after,
            cause_code=cause_code,
        )

    def with_context(self, strategy_id: str, context_key: str) -> Self:
        return replace(self, strategy_id=strategy_id, context_key=context_key)
