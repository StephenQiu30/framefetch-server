"""Automatic processing status; masks are an internal implementation detail."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class WatermarkTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    job_id: UUID
    status: Literal[
        "queued", "running", "succeeded", "unchanged", "failed", "cancelled"
    ]
    attempt: int
    size_bytes: int
    error_code: str | None
    created_at: datetime


class WatermarkListResponse(BaseModel):
    available: bool
    items: list[WatermarkTaskResponse]
