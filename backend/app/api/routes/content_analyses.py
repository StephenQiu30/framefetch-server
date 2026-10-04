"""Content intake and revision use existing durable task/report ownership."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.admission import RateLimitAdmission
from app.api.deps import IdempotencyKey, get_analysis_use_cases, get_current_user
from app.api.responses import ApiResponseRoute
from app.core.runtime import AnalysisUseCases
from app.schemas.analyses import (
    AnalysisResponse,
    ContentAnalysisRequest,
    ContentRevisionRequest,
)
from app.services.analysis.content_versions import ContentVersion
from app.services.analysis.errors import (
    AnalysisApplicationError,
    AnalysisApplicationErrorCode,
)
from app.services.analysis.rules.content_document import ContentSourceSet
from app.services.auth.models import CurrentUser

router = APIRouter(route_class=ApiResponseRoute, tags=["analyses"])
User = Annotated[CurrentUser, Depends(get_current_user)]
UseCases = Annotated[AnalysisUseCases, Depends(get_analysis_use_cases)]


@router.post(
    "/content/analyses",
    operation_id="createContentAnalysis",
    response_model=AnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RateLimitAdmission("analysis"))],
    summary="从文字材料创作文章、帖子或说明文档",
)
async def create_content_analysis(
    body: ContentAnalysisRequest,
    idempotency_key: IdempotencyKey,
    response: Response,
    user: User,
    use_cases: UseCases,
) -> AnalysisResponse:
    if use_cases.create_content_analysis is None:
        raise AnalysisApplicationError(AnalysisApplicationErrorCode.SERVICE_UNAVAILABLE)
    view = await use_cases.create_content_analysis(
        body.source,
        body.output_language,
        user.owner_hash,
        idempotency_key,
        quota=user.admission_quota,
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Location"] = f"/api/analyses/{view.id}"
    return AnalysisResponse.from_view(view)


@router.get(
    "/content/analyses/{analysis_id}/source",
    operation_id="getContentSource",
    response_model=ContentSourceSet,
    summary="回看本次创作的原始材料",
)
async def get_content_source(
    analysis_id: UUID, response: Response, user: User, use_cases: UseCases
) -> ContentSourceSet:
    if use_cases.get_content_source is None:
        raise AnalysisApplicationError(AnalysisApplicationErrorCode.SERVICE_UNAVAILABLE)
    response.headers["Cache-Control"] = "private, no-store"
    return await use_cases.get_content_source(analysis_id, user.owner_hash)


@router.post(
    "/content/analyses/{analysis_id}/revisions",
    operation_id="reviseContent",
    response_model=AnalysisResponse,
    status_code=201,
    dependencies=[Depends(RateLimitAdmission("analysis"))],
    summary="保存人工修订稿，保留原版本",
)
async def revise_content(
    analysis_id: UUID,
    body: ContentRevisionRequest,
    idempotency_key: IdempotencyKey,
    response: Response,
    user: User,
    use_cases: UseCases,
) -> AnalysisResponse:
    if use_cases.revise_content is None:
        raise AnalysisApplicationError(AnalysisApplicationErrorCode.SERVICE_UNAVAILABLE)
    response.headers["Cache-Control"] = "private, no-store"
    return AnalysisResponse.from_view(
        await use_cases.revise_content(
            analysis_id,
            user.owner_hash,
            body.base_report_id,
            body.draft,
            idempotency_key,
            quota=user.admission_quota,
        )
    )


@router.get(
    "/content/analyses/{analysis_id}/versions",
    operation_id="listContentVersions",
    response_model=tuple[ContentVersion, ...],
    summary="回看已保存的正文版本",
)
async def list_content_versions(
    analysis_id: UUID, response: Response, user: User, use_cases: UseCases
) -> tuple[ContentVersion, ...]:
    if use_cases.list_content_versions is None:
        raise AnalysisApplicationError(AnalysisApplicationErrorCode.SERVICE_UNAVAILABLE)
    response.headers["Cache-Control"] = "private, no-store"
    return await use_cases.list_content_versions(analysis_id, user.owner_hash)
