"""Owner-scoped immutable content versions, excluding unpublished reports."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.services.analysis.errors import (
    AnalysisApplicationError,
    AnalysisApplicationErrorCode,
    PersistenceNotFound,
)
from app.services.analysis.rules.content_document import (
    ContentDocumentResult,
    ContentModel,
)
from app.services.analysis.validation import validate_owner_hash


class ContentVersion(ContentModel):
    id: UUID
    run_no: int
    created_at: datetime
    result: ContentDocumentResult
    markdown: str
    content_sha256: str


class ContentVersionPersistence(Protocol):
    async def content_versions(
        self, job_id: UUID, owner_hash: str
    ) -> tuple[ContentVersion, ...]: ...


class ListContentVersions:
    def __init__(self, repository: ContentVersionPersistence) -> None:
        self._repository = repository

    async def __call__(
        self, job_id: UUID, owner_hash: str
    ) -> tuple[ContentVersion, ...]:
        try:
            return await self._repository.content_versions(
                job_id, validate_owner_hash(owner_hash)
            )
        except PersistenceNotFound as error:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.NOT_FOUND
            ) from error
