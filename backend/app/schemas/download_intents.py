from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import StrictModel
from app.schemas.inspections import DiscoveredItemInspectionSource
from app.services.downloads.intent_models import (
    IntentHistoryPage,
    IntentSnapshot,
    IntentStatus,
)
from app.services.provider_failures import FailureClass, ProviderFailure

IntentNextAction = Literal["none", "wait", "refresh_result", "import_file"]


class IntentRequest(StrictModel):
    input: str | None = Field(
        default=None,
        min_length=8,
        max_length=4096,
        description="媒体地址或包含唯一媒体地址的分享文案。",
    )
    source: DiscoveredItemInspectionSource | None = None

    @model_validator(mode="after")
    def require_one_source(self) -> "IntentRequest":
        if (self.input is None) == (self.source is None):
            raise ValueError("exactly one parsing source is required")
        return self


class IntentFailureResponse(StrictModel):
    code: str
    failure_class: FailureClass
    layer: str
    stage: Literal["resolve", "download", "validate", "publish"]
    gate: Literal["①", "②", "③", "none"]
    evidence: dict[str, str | int | bool | None]
    summary: str

    @classmethod
    def from_failure(cls, failure: ProviderFailure) -> "IntentFailureResponse":
        return cls(
            code=failure.code,
            failure_class=failure.failure_class,
            layer=failure.layer,
            stage=failure.stage,
            gate=failure.gate,
            evidence=failure.evidence,
            summary=failure.summary,
        )


class IntentResponse(StrictModel):
    id: UUID
    version: int
    status: IntentStatus
    reason_code: str | None
    failure: IntentFailureResponse | None
    next_action: IntentNextAction = "none"
    deadline: datetime
    inspection_id: UUID | None
    job_id: UUID | None

    @classmethod
    def from_snapshot(cls, value: IntentSnapshot) -> "IntentResponse":
        failure = value.latest_failure
        next_action: IntentNextAction = "none"
        if value.status in {
            IntentStatus.QUEUED,
            IntentStatus.RESOLVING,
            IntentStatus.CANCELLING,
        }:
            next_action = "wait"
        elif value.status in {IntentStatus.FAILED, IntentStatus.EXPIRED}:
            next_action = (
                "import_file"
                if failure
                and failure.failure_class
                in {
                    FailureClass.CONTENT_PROTECTED,
                    FailureClass.LOGIN_REQUIRED,
                }
                else "refresh_result"
            )
        return cls(
            id=value.id,
            version=value.version,
            status=value.status,
            reason_code=value.reason_code,
            next_action=next_action,
            failure=None
            if failure is None
            else IntentFailureResponse.from_failure(failure),
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
