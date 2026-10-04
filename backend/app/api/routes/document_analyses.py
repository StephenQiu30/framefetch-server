from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.admission import RateLimitAdmission
from app.api.deps import IdempotencyKey, get_analysis_use_cases, get_current_user
from app.api.responses import ApiResponseRoute
from app.core.runtime import AnalysisUseCases
from app.schemas.analyses import AnalysisRequest, AnalysisResponse
from app.services.auth.models import CurrentUser

router = APIRouter(route_class=ApiResponseRoute, tags=["analyses"])
User = Annotated[CurrentUser, Depends(get_current_user)]
UseCases = Annotated[AnalysisUseCases, Depends(get_analysis_use_cases)]


@router.post(
    "/documents/{document_id}/analyses",
    operation_id="createDocumentAnalysis",
    response_model=AnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RateLimitAdmission("analysis"))],
    summary="创建剧本分析任务",
)
async def create_document_analysis(
    document_id: UUID,
    body: AnalysisRequest,
    idempotency_key: IdempotencyKey,
    response: Response,
    user: User,
    use_cases: UseCases,
) -> AnalysisResponse:
    view = await use_cases.create_document_analysis(
        document_id,
        user.owner_hash,
        idempotency_key,
        body.skill_id,
        body.output_language,
        body.custom_prompt,
        quota=user.admission_quota,
    )
    response.headers["Location"] = f"/api/analyses/{view.id}"
    response.headers["Cache-Control"] = "private, no-store"
    return AnalysisResponse.from_view(view)


@router.get(
    "/documents/{document_id}/analysis",
    operation_id="getLatestDocumentAnalysis",
    response_model=AnalysisResponse | None,
    summary="读取文档最近的剧本分析",
)
async def get_latest_document_analysis(
    document_id: UUID,
    user: User,
    use_cases: UseCases,
) -> AnalysisResponse | None:
    """恢复当前用户在该剧本文档上最近创建的分析与报告。"""
    view = await use_cases.get_latest_document_analysis(document_id, user.owner_hash)
    return None if view is None else AnalysisResponse.from_view(view)
