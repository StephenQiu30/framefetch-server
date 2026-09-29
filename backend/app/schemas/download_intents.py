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


class IntentRequest(StrictModel):
    input: str = Field(
        min_length=8,
        max_length=4096,
        description="公开媒体地址或包含唯一媒体地址的分享文案。",
    )


class IntentResumeRequest(StrictModel):
    authorization_id: UUID


class IntentResponse(StrictModel):
    id: UUID
    version: int
    status: IntentStatus
    reason_code: str | None
    next_action: Literal["none", "login"] = "none"
    authorization_id: UUID | None = None
    authorization_deadline: datetime | None = None
    retry_at: datetime | None
    deadline: datetime
    inspection_id: UUID | None
    job_id: UUID | None

    @classmethod
    def from_snapshot(cls, value: IntentSnapshot) -> "IntentResponse":
        return cls(
            id=value.id,
            version=value.version,
            status=value.status,
            reason_code=value.reason_code,
            next_action="login"
            if value.status is IntentStatus.ACTION_REQUIRED
            else "none",
            authorization_id=value.authorization_id,
            authorization_deadline=value.authorization_deadline,
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
