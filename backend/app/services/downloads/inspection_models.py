from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.services.downloads.rules.enums import MediaKind
from app.services.downloads.rules.formats import DownloadPlan
from app.services.downloads.rules.inspection import (
    AccessDecision,
    EntitlementState,
    ExecutionMode,
    IdentityState,
    ProtectionState,
    RightsBasis,
    SourceOrigin,
)
from app.services.provider_types import ExecutionContext


@dataclass(frozen=True, slots=True)
class EncryptedUrl:
    ciphertext: bytes
    nonce: bytes
    key_id: str

    def __post_init__(self) -> None:
        if not self.ciphertext or not self.nonce or not self.key_id.strip():
            raise ValueError("encrypted URL envelope is incomplete")


@dataclass(frozen=True, slots=True)
class RunnerFormat:
    display_name: str
    plan: DownloadPlan | None
    media_kind: MediaKind = MediaKind.VIDEO
    asset_count: int = 0


@dataclass(frozen=True, slots=True)
class RunnerInspection:
    extractor_key: str
    provider_media_id: str
    title: str
    duration_seconds: int
    formats: tuple[RunnerFormat, ...]
    execution_context: ExecutionContext
    thumbnail_data_url: str | None = None
    media_kind: MediaKind = MediaKind.VIDEO
    asset_count: int = 0


@dataclass(frozen=True, slots=True)
class FormatCreate:
    id: UUID
    display_name: str
    plan_fingerprint: str
    semantic_plan: dict[str, object]
    provider_hints: dict[str, object]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class InspectionCreate:
    id: UUID
    owner_hash: str
    idempotency_key: str
    request_fingerprint: str
    url_ciphertext: bytes
    url_nonce: bytes
    url_key_id: str
    extractor_key: str
    provider_media_id: str
    title: str
    duration_seconds: int
    metadata: dict[str, object]
    expires_at: datetime
    formats: tuple[FormatCreate, ...]


@dataclass(frozen=True, slots=True)
class FormatSnapshot:
    id: UUID
    display_name: str
    plan_fingerprint: str
    semantic_plan: dict[str, object]
    provider_hints: dict[str, object]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class InspectionSnapshot:
    id: UUID
    owner_hash: str
    request_fingerprint: str
    extractor_key: str
    provider_media_id: str
    title: str
    duration_seconds: int
    metadata: dict[str, object]
    expires_at: datetime
    formats: tuple[FormatSnapshot, ...]
    thumbnail_available: bool = False


@dataclass(frozen=True, slots=True)
class InspectionSaveResult:
    inspection: InspectionSnapshot
    created: bool


@dataclass(frozen=True, slots=True)
class FormatView:
    id: UUID
    display_name: str
    plan: DownloadPlan | None


@dataclass(frozen=True, slots=True)
class InspectionView:
    id: UUID
    extractor_key: str
    provider_media_id: str
    title: str
    duration_seconds: int
    expires_at: datetime
    formats: tuple[FormatView, ...]
    thumbnail_url: str | None = None
    source_origin: SourceOrigin = SourceOrigin.PUBLIC_URL
    execution_mode: ExecutionMode = ExecutionMode.PROVIDER_RUNNER
    access_decision: AccessDecision = AccessDecision.DOWNLOADABLE
    entitlement_state: EntitlementState = EntitlementState.PUBLIC_FREE
    identity_state: IdentityState = IdentityState.VERIFIED
    protection_state: ProtectionState = ProtectionState.CLEAR
    rights_basis: RightsBasis | None = RightsBasis.PUBLIC_ACCESS
    restriction_reason: str | None = None
    user_action: str | None = None
    media_kind: MediaKind = MediaKind.VIDEO
    asset_count: int = 0
