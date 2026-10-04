"""Content intake and read-only reports use existing task ownership."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.deps import get_analysis_use_cases, get_current_user
from app.api.responses import ApiResponseRoute
from app.core.runtime import AnalysisUseCases
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


@router.get(
    "/content/analyses/{analysis_id}/versions",
    operation_id="listContentVersions",
    response_model=tuple[ContentVersion, ...],
    summary="只读回看已发布的历史报告",
)
async def list_content_versions(
    analysis_id: UUID, response: Response, user: User, use_cases: UseCases
) -> tuple[ContentVersion, ...]:
    if use_cases.list_content_versions is None:
        raise AnalysisApplicationError(AnalysisApplicationErrorCode.SERVICE_UNAVAILABLE)
    response.headers["Cache-Control"] = "private, no-store"
    return await use_cases.list_content_versions(analysis_id, user.owner_hash)
