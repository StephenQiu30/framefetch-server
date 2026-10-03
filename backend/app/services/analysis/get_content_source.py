"""Owner-scoped retrieval of the exact materials used by a content task."""

from uuid import UUID

from app.services.analysis.errors import (
    AnalysisApplicationError,
    AnalysisApplicationErrorCode,
)
from app.services.analysis.ports import AnalysisRepository
from app.services.analysis.rules.content_document import ContentSourceSet
from app.services.analysis.validation import validate_owner_hash


class GetContentSource:
    def __init__(self, repository: AnalysisRepository) -> None:
        self._repository = repository

    async def __call__(self, job_id: UUID, owner_hash: str) -> ContentSourceSet:
        job = await self._repository.get_job(job_id)
        if (
            job is None
            or job.owner_hash != validate_owner_hash(owner_hash)
            or job.input_kind != "content"
            or job.content_source is None
        ):
            raise AnalysisApplicationError(AnalysisApplicationErrorCode.NOT_FOUND)
        if job.content_source.sha256 != job.input_sha256:
            raise AnalysisApplicationError(AnalysisApplicationErrorCode.INTERNAL_ERROR)
        return job.content_source
