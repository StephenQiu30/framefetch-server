from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.services.downloads.inspection_models import EncryptedUrl
from app.services.source_discovery import (
    DiscoveryDecisionHint,
    DiscoveryItemKind,
    DiscoveryItemStatus,
    DiscoveryStatus,
)


@dataclass(frozen=True, slots=True)
class ArticleDiscoveryCandidate:
    kind: DiscoveryItemKind
    child_provider: str | None
    title: str
    duration_ms: int | None
    identity_evidence_hash: str
    decision_hint: DiscoveryDecisionHint
    status: DiscoveryItemStatus
    source_url: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ArticleDiscoveryResult:
    title: str
    items: tuple[ArticleDiscoveryCandidate, ...]


@dataclass(frozen=True, slots=True)
class SourceDiscoveryItemCreate:
    id: UUID
    item_ref: UUID
    position: int
    kind: DiscoveryItemKind
    child_provider: str | None
    title: str
    duration_ms: int | None
    identity_evidence_hash: str
    decision_hint: DiscoveryDecisionHint
    status: DiscoveryItemStatus


@dataclass(frozen=True, slots=True)
class SourceDiscoveryCreate:
    id: UUID
    owner_hash: str
    idempotency_key: str
    request_fingerprint: str
    encrypted_url: EncryptedUrl
    source_fingerprint: str
    provider_key: str
    title: str
    adapter_version: str
    status: DiscoveryStatus
    expires_at: datetime
    items: tuple[SourceDiscoveryItemCreate, ...]


@dataclass(frozen=True, slots=True)
class SourceDiscoveryItemSnapshot:
    item_ref: UUID
    position: int
    kind: DiscoveryItemKind
    child_provider: str | None
    title: str
    duration_ms: int | None
    identity_evidence_hash: str
    decision_hint: DiscoveryDecisionHint
    status: DiscoveryItemStatus


@dataclass(frozen=True, slots=True)
class SourceDiscoverySnapshot:
    id: UUID
    owner_hash: str
    request_fingerprint: str
    encrypted_url: EncryptedUrl
    source_fingerprint: str
    provider_key: str
    title: str
    adapter_version: str
    status: DiscoveryStatus
    expires_at: datetime
    created_at: datetime
    items: tuple[SourceDiscoveryItemSnapshot, ...]


@dataclass(frozen=True, slots=True)
class SourceDiscoverySaveResult:
    discovery: SourceDiscoverySnapshot
    created: bool


@dataclass(frozen=True, slots=True)
class SourceDiscoveryItemSelection:
    discovery: SourceDiscoverySnapshot
    item: SourceDiscoveryItemSnapshot


@dataclass(frozen=True, slots=True)
class SourceDiscoveryItemView:
    item_ref: UUID
    kind: DiscoveryItemKind
    title: str
    duration_ms: int | None
    decision_hint: DiscoveryDecisionHint
    status: DiscoveryItemStatus


@dataclass(frozen=True, slots=True)
class SourceDiscoveryView:
    id: UUID
    provider_key: str
    title: str
    status: DiscoveryStatus
    expires_at: datetime
    items: tuple[SourceDiscoveryItemView, ...]
