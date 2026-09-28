from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_provider_statuses
from app.api.responses import ApiResponseRoute
from app.schemas.providers import ProviderListResponse
from app.services.auth.models import CurrentUser
from app.services.providers import ProviderStatusView

router = APIRouter(
    route_class=ApiResponseRoute, prefix="/providers", tags=["providers"]
)
User = Annotated[CurrentUser, Depends(get_current_user)]
Statuses = Annotated[tuple[ProviderStatusView, ...], Depends(get_provider_statuses)]


@router.get(
    "",
    operation_id="listProviders",
    response_model=ProviderListResponse,
    summary="查询平台能力状态",
)
async def list_providers(user: User, statuses: Statuses) -> ProviderListResponse:
    """返回不含凭据、出口地址和 Canary 目标的能力快照。"""
    return ProviderListResponse.from_views(statuses)
