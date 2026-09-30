from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import StrictModel
from app.services.downloads.intent_models import (
    IntentHistoryPage,
    IntentSnapshot,
    IntentStatus,
)
from app.services.provider_failures import (
    FailureClass,
    FailureEvidenceKind,
    FailurePhase,
    FailureScope,
    ProviderFailure,
)

IntentNextAction = Literal["none", "wait", "refresh_result", "import_file"]


def intent_resolution_state(
    status: IntentStatus, failure: ProviderFailure | None
) -> tuple[FailurePhase | None, IntentNextAction]:
    next_action: IntentNextAction = "none"
    if status in {
        IntentStatus.QUEUED,
        IntentStatus.PREPARING,
        IntentStatus.RESOLVING,
        IntentStatus.RETRY_WAIT,
    }:
        next_action = "wait"
    elif status in {IntentStatus.FAILED, IntentStatus.EXPIRED}:
        next_action = (
            "import_file"
            if failure is not None
            and (
                failure.scope is FailureScope.SESSION
                or failure.failure_class
                in {
                    FailureClass.CHALLENGE_REQUIRED,
                    FailureClass.SOURCE_UNSUPPORTED,
                    FailureClass.CONTENT_RESTRICTED,
                    FailureClass.OUTCOME_UNKNOWN,
                }
            )
            else "refresh_result"
        )
    phase = (
        failure.phase
        if failure is not None
        and status
        in {IntentStatus.RETRY_WAIT, IntentStatus.FAILED, IntentStatus.EXPIRED}
        else {
            IntentStatus.QUEUED: FailurePhase.RECOGNIZE,
            IntentStatus.PREPARING: FailurePhase.PREPARE_CONTEXT,
            IntentStatus.RESOLVING: FailurePhase.FETCH_METADATA,
            IntentStatus.READY: FailurePhase.SELECT_FORMAT,
            IntentStatus.HANDED_OFF: FailurePhase.TRANSFER,
        }.get(status)
    )
    return phase, next_action


class IntentRequest(StrictModel):
    input: str = Field(
        min_length=8,
        max_length=4096,
        description="公开媒体地址或包含唯一媒体地址的分享文案。",
    )


class IntentFailureResponse(StrictModel):
    code: str
    phase: FailurePhase
    scope: FailureScope
    failure_class: FailureClass
    cause_code: str | None
    evidence_kind: FailureEvidenceKind
    observed_at: datetime
    retry_after: datetime | None
    diagnostic_ref: str | None

    @classmethod
    def from_failure(cls, failure: ProviderFailure) -> "IntentFailureResponse":
        return cls(
            code=failure.code,
            phase=failure.phase,
            scope=failure.scope,
            failure_class=failure.failure_class,
            cause_code=failure.cause_code,
            evidence_kind=failure.evidence_kind,
            observed_at=failure.observed_at,
            retry_after=failure.retry_after,
            diagnostic_ref=failure.diagnostic_ref,
        )


class IntentResponse(StrictModel):
    id: UUID
    version: int
    status: IntentStatus
    reason_code: str | None
    phase: FailurePhase | None
    failure: IntentFailureResponse | None
    next_action: IntentNextAction = "none"
    retry_at: datetime | None
    deadline: datetime
    inspection_id: UUID | None
    job_id: UUID | None

    @classmethod
    def from_snapshot(cls, value: IntentSnapshot) -> "IntentResponse":
        failure = value.latest_failure
        phase, next_action = intent_resolution_state(value.status, failure)
        return cls(
            id=value.id,
            version=value.version,
            status=value.status,
            reason_code=value.reason_code,
            next_action=next_action,
            phase=phase,
            failure=None
            if failure is None
            else IntentFailureResponse.from_failure(failure),
            retry_at=value.retry_at,
            deadline=value.deadline,
            inspection_id=value.inspection_id,
            job_id=value.job_id,
        )


class IntentHistoryItemResponse(IntentResponse):
    created_at: datetime
    title: str | None


class IntentHistoryResponse(StrictModel):
    items: list[IntentHistoryItemResponse]
    next_cursor: UUID | None

    @classmethod
    def from_page(cls, page: IntentHistoryPage) -> "IntentHistoryResponse":
        return cls(
            items=[
                IntentHistoryItemResponse(
                    **IntentResponse.from_snapshot(item.intent).model_dump(),
                    created_at=item.intent.created_at,
                    title=item.title,
                )
                for item in page.items
            ],
            next_cursor=page.next_cursor,
        )
