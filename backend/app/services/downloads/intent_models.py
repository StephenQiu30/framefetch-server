"""One durable parse intent; the existing inspection and job own their results."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.services.downloads.inspection_models import EncryptedUrl
from app.services.downloads.resolution import ResolutionExecution, ResolutionPlan
from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_failures import ProviderFailure


class IntentStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    RESOLVING = "resolving"
    RETRY_WAIT = "retry_wait"
    ACTION_REQUIRED = "action_required"
    READY = "ready"
    HANDED_OFF = "handed_off"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"


RUNNING_INTENT_STATUSES = (
    IntentStatus.PREPARING,
    IntentStatus.RESOLVING,
)
TERMINAL_INTENT_STATUSES = (
    IntentStatus.CANCELLED,
    IntentStatus.EXPIRED,
    IntentStatus.FAILED,
    IntentStatus.HANDED_OFF,
)
ACTIVE_INTENT_STATUSES = (
    IntentStatus.QUEUED,
    *RUNNING_INTENT_STATUSES,
    IntentStatus.RETRY_WAIT,
    IntentStatus.ACTION_REQUIRED,
)


@dataclass(frozen=True, slots=True)
class IntentCreate:
    id: UUID
    owner_hash: str
    idempotency_key: str
    request_fingerprint: str
    url: EncryptedUrl = field(repr=False)
    access_policy: ProviderAccessPolicy = ProviderAccessPolicy.PUBLIC


@dataclass(frozen=True, slots=True)
class IntentSnapshot:
    id: UUID
    owner_hash: str
    status: IntentStatus
    access_policy: ProviderAccessPolicy
    version: int
    fence: int
    attempt: int
    max_attempts: int
    remaining_budget_ms: int
    deadline: datetime
    generation: int
    operation_id: str | None
    retry_at: datetime | None
    inspection_id: UUID | None
    job_id: UUID | None
    reason_code: str | None
    created_at: datetime
    updated_at: datetime
    authorization_id: UUID | None = None
    authorization_deadline: datetime | None = None
    resolution_plan: ResolutionPlan | None = None
    next_strategy_id: str | None = None
    selected_operation_id: str | None = None
    latest_failure: ProviderFailure | None = None


@dataclass(frozen=True, slots=True)
class IntentOperation:
    intent: IntentSnapshot
    url: EncryptedUrl = field(repr=False)
    newly_claimed: bool = True
    execution: ResolutionExecution | None = None


@dataclass(frozen=True, slots=True)
class IntentHistoryEntry:
    intent: IntentSnapshot
    title: str | None


@dataclass(frozen=True, slots=True)
class IntentHistoryPage:
    items: tuple[IntentHistoryEntry, ...]
    next_cursor: UUID | None
