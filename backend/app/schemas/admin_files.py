from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.common import StrictModel
from app.services.storage_files.models import (
    StorageCleanupResult,
    StoredFileCategory,
    StoredFilePage,
)


class StoredFileResponse(StrictModel):
    id: UUID
    category: StoredFileCategory
    name: str = Field(min_length=1, max_length=512)
    uploader_username: str | None = Field(
        default=None,
        min_length=2,
        max_length=32,
        description="文件所属账号的当前用户名；无法关联账号时为空。报告使用分析任务发起账号。",
    )
    object_count: int = Field(ge=1)
    size_bytes: int = Field(gt=0)
    created_at: datetime


class StoredFileListResponse(StrictModel):
    items: list[StoredFileResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=50)
    total: int = Field(ge=0)

    @classmethod
    def from_page(cls, page: StoredFilePage) -> StoredFileListResponse:
        return cls.model_validate(page)


class StorageCleanupRequest(StrictModel):
    older_than_days: int = Field(default=30, ge=1, le=3_650)


class StorageCleanupResponse(StrictModel):
    older_than_days: int = Field(ge=1, le=3_650)
    removed_resources: int = Field(ge=0)
    removed_objects: int = Field(ge=0)
    freed_bytes: int = Field(ge=0)
    failed_resources: int = Field(ge=0)

    @classmethod
    def from_result(cls, result: StorageCleanupResult) -> StorageCleanupResponse:
        return cls.model_validate(result)
