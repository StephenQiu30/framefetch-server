from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_analysis_use_cases, get_current_user
from app.api.responses import ApiResponseRoute
from app.core.runtime import AnalysisUseCases
from app.schemas.analyses import AnalysisResponse
from app.services.auth.models import CurrentUser

router = APIRouter(route_class=ApiResponseRoute, tags=["analyses"])
User = Annotated[CurrentUser, Depends(get_current_user)]
UseCases = Annotated[AnalysisUseCases, Depends(get_analysis_use_cases)]


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
