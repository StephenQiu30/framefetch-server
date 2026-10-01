"""Failure facts shared by provider execution and business rules; no I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Literal, Self

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
    ROUTE = "route"
    DEPENDENCY = "dependency"
    RUNTIME = "runtime"


class FailureClass(StrEnum):
    NETWORK_BLOCKED = "network_blocked"
    CHALLENGE = "challenge"
    LOGIN_REQUIRED = "login_required"
    IDENTITY_UNAVAILABLE = "identity_unavailable"
    RATE_LIMITED = "rate_limited"
    CONTEXT_CHANGED = "context_changed"
    CONTENT_UNAVAILABLE = "content_unavailable"
    CONTENT_PROTECTED = "content_protected"
    EXTRACTOR_BROKEN = "extractor_broken"
    FORMAT_UNAVAILABLE = "format_unavailable"
    TRANSIENT = "transient"
    INVALID_INPUT = "invalid_input"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"


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


for _kind in FailureClass:
    _define((_kind.value,), _kind, FailureScope.CONTENT)

_define(
    ("egress_denied", "provider_geo_restricted"),
    FailureClass.NETWORK_BLOCKED,
    FailureScope.ROUTE,
)
_define(
    ("egress_challenged", "challenge_required", "pot_required", "pot_rejected"),
    FailureClass.CHALLENGE,
    FailureScope.ROUTE,
)
_define(("provider_auth_required",), FailureClass.LOGIN_REQUIRED, FailureScope.CONTENT)
_define(
    (
        "provider_link_unavailable",
        "content_deleted",
        "content_private",
        "content_not_entitled",
        "content_entitlement_unknown",
        "content_access_metadata_invalid",
        "content_preview_only",
        "content_supporter_only",
        "content_paid_only",
        "content_export_required",
        "provider_content_restricted",
    ),
    FailureClass.CONTENT_UNAVAILABLE,
    FailureScope.CONTENT,
)
_define(("provider_rate_limited",), FailureClass.RATE_LIMITED, FailureScope.ROUTE)
_define(
    ("source_changed", "client_context_mismatch"),
    FailureClass.CONTEXT_CHANGED,
    FailureScope.CONTENT,
    FailurePhase.SELECT_FORMAT,
)
_define(("drm_protected",), FailureClass.CONTENT_PROTECTED, FailureScope.CONTENT)
_define(
    (
        "extractor_regression",
        "upstream_unclassified",
        "inspection_failed",
        "download_failed",
    ),
    FailureClass.EXTRACTOR_BROKEN,
    FailureScope.DEPENDENCY,
)
_define(
    (
        "protocol_unavailable",
        "transcode_required",
        "format_limit_exceeded",
    ),
    FailureClass.FORMAT_UNAVAILABLE,
    FailureScope.CONTENT,
    FailurePhase.SELECT_FORMAT,
)
_define(
    (
        "network_transient",
        "download_timeout",
        "inspection_timeout",
        "cancelled",
        "cancellation_pending",
        "storage_unavailable",
        "publish_failed",
    ),
    FailureClass.TRANSIENT,
    FailureScope.ROUTE,
)
_define(
    (
        "invalid_url",
        "invalid_request",
        "request_too_large",
        "task_not_found",
        "authentication_required",
        "invalid_signature",
        "signature_expired",
        "request_replayed",
        "provider_unsupported",
        "provider_media_unsupported",
        "unsupported_source",
        "duration_limit_exceeded",
    ),
    FailureClass.INVALID_INPUT,
    FailureScope.CONTENT,
    FailurePhase.RECOGNIZE,
)
_define(
    (
        "runner_unavailable",
        "runner_dependency_unavailable",
        "engine_unavailable",
        "engine_catalog_unavailable",
        "runner_restarted",
        "internal_error",
        "runner_busy",
        "workspace_limit_exceeded",
        "task_already_active",
        "invalid_runner_response",
        "browser_unavailable",
        "browser_capacity_exhausted",
        "browser_profile_limit",
        "pot_provider_unavailable",
    ),
    FailureClass.RUNTIME_UNAVAILABLE,
    FailureScope.RUNTIME,
    FailurePhase.PREPARE_CONTEXT,
)
_define(
    ("invalid_artifact", "remux_failed", "media_probe_failed"),
    FailureClass.EXTRACTOR_BROKEN,
    FailureScope.CONTENT,
    FailurePhase.VALIDATE,
)


def failure_definition(code: str) -> tuple[FailureClass, FailureScope, FailurePhase]:
    return _DEFINITIONS.get(
        code,
        (
            FailureClass.EXTRACTOR_BROKEN,
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
    layer: str = "L1"
    stage: Literal["resolve", "download", "validate", "publish"] = "resolve"
    summary: str = "Media execution failed"
    gate: Literal["①", "②", "③", "none"] = "none"
    evidence: dict[str, str | int | bool | None] = field(default_factory=dict)
    retry_after: datetime | None = None
    diagnostic_ref: str | None = None
    cause_code: str | None = None

    def __post_init__(self) -> None:
        kind, _, _ = failure_definition(self.code)
        if self.failure_class is not kind:
            raise ValueError("provider failure class does not match its code")
        if _CODE.fullmatch(self.code) is None or (
            self.cause_code is not None and _CODE.fullmatch(self.cause_code) is None
        ):
            raise ValueError("provider failure code is invalid")
        if any(
            value is not None and _REFERENCE.fullmatch(value) is None
            for value in (self.diagnostic_ref,)
        ):
            raise ValueError("provider failure reference is invalid")
        if self.layer not in {"L1", "L2", "L3"} or self.stage not in {
            "resolve",
            "download",
            "validate",
            "publish",
        }:
            raise ValueError("provider failure execution location is invalid")
        if self.gate not in {"①", "②", "③", "none"}:
            raise ValueError("provider failure gate is invalid")
        if not self.evidence:
            object.__setattr__(
                self,
                "evidence",
                {
                    "kind": self.evidence_kind.value,
                    **({"cause_code": self.cause_code} if self.cause_code else {}),
                },
            )
        if set(self.evidence) - {
            "kind",
            "cause_code",
            "http_status",
            "returncode",
            "stderr_truncated",
        }:
            raise ValueError("provider failure evidence contains unsupported facts")
        if self.evidence.get("kind") != self.evidence_kind.value:
            raise ValueError("provider failure evidence kind does not match")
        cause = self.evidence.get("cause_code")
        if cause is not None and (
            not isinstance(cause, str) or _CODE.fullmatch(cause) is None
        ):
            raise ValueError("provider failure evidence cause is invalid")
        for name in ("http_status", "returncode"):
            value = self.evidence.get(name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int)
            ):
                raise ValueError("provider failure evidence status is invalid")
        http_status = self.evidence.get("http_status")
        if http_status is not None and (
            not isinstance(http_status, int) or not 100 <= http_status <= 599
        ):
            raise ValueError("provider failure HTTP status is invalid")
        if "stderr_truncated" in self.evidence and not isinstance(
            self.evidence["stderr_truncated"], bool
        ):
            raise ValueError("provider failure evidence truncation is invalid")
        if not self.summary.strip() or len(self.summary) > 256:
            raise ValueError("provider failure summary is invalid")
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
        layer: str = "L1",
        stage: Literal["resolve", "download", "validate", "publish"] | None = None,
        summary: str | None = None,
        gate: Literal["①", "②", "③", "none"] = "none",
        evidence: dict[str, str | int | bool | None] | None = None,
    ) -> Self:
        kind, default_scope, default_phase = failure_definition(code)
        return cls(
            code,
            phase or default_phase,
            scope or default_scope,
            kind,
            evidence_kind,
            layer=layer,
            stage=stage
            or (
                "publish"
                if (phase or default_phase) is FailurePhase.PUBLISH
                else "validate"
                if (phase or default_phase)
                in {FailurePhase.VALIDATE, FailurePhase.PROBE_MEDIA}
                else "download"
                if (phase or default_phase) is FailurePhase.TRANSFER
                else "resolve"
            ),
            summary=summary or kind.value.replace("_", " "),
            gate=gate,
            evidence=evidence or {},
            retry_after=retry_after,
            cause_code=cause_code,
        )
