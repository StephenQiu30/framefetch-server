"""One durable parse intent; the existing inspection and job own their results."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.services.downloads.inspection_models import EncryptedUrl
from app.services.provider_failures import ProviderFailure
from app.services.provider_types import ExecutionContext


class IntentStatus(StrEnum):
    QUEUED = "queued"
    RESOLVING = "resolving"
    READY = "ready"
    HANDED_OFF = "handed_off"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"


RUNNING_INTENT_STATUSES = (IntentStatus.RESOLVING,)
TERMINAL_INTENT_STATUSES = (
    IntentStatus.CANCELLED,
    IntentStatus.EXPIRED,
    IntentStatus.FAILED,
    IntentStatus.HANDED_OFF,
)
ACTIVE_INTENT_STATUSES = (
    IntentStatus.QUEUED,
    *RUNNING_INTENT_STATUSES,
    IntentStatus.CANCELLING,
)


@dataclass(frozen=True, slots=True)
class IntentCreate:
    id: UUID
    owner_hash: str
    idempotency_key: str
    request_fingerprint: str
    url: EncryptedUrl = field(repr=False)


@dataclass(frozen=True, slots=True)
class IntentSnapshot:
    id: UUID
    owner_hash: str
    status: IntentStatus
    version: int
    deadline: datetime
    generation: int
    inspection_id: UUID | None
    job_id: UUID | None
    reason_code: str | None
    created_at: datetime
    updated_at: datetime
    execution_context: ExecutionContext | None = None
    latest_failure: ProviderFailure | None = None


@dataclass(frozen=True, slots=True)
class IntentOperation:
    intent: IntentSnapshot
    url: EncryptedUrl = field(repr=False)


@dataclass(frozen=True, slots=True)
class IntentHistoryEntry:
    intent: IntentSnapshot
    title: str | None


@dataclass(frozen=True, slots=True)
class IntentHistoryPage:
    items: tuple[IntentHistoryEntry, ...]
    next_cursor: UUID | None
