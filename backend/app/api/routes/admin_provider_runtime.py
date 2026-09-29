from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import (
    get_current_admin,
    get_provider_statuses,
    get_services,
    require_service,
)
from app.api.responses import ApiResponseRoute
from app.core.errors import AppError
from app.integrations.media_runner_models import MediaRunnerClientError
from app.schemas.engine_catalog import EngineCatalogResponse
from app.schemas.provider_runtime import (
    ProviderRuntimeListResponse,
    ProviderRuntimeResponse,
)
from app.services.auth.models import CurrentUser
from app.services.providers import ProviderStatusView

router = APIRouter(
    route_class=ApiResponseRoute, prefix="/admin/provider-runtime", tags=["admin"]
)


@router.get(
    "/engine-catalog",
    operation_id="getAdminEngineCatalog",
    response_model=EngineCatalogResponse,
    summary="读取会话 Runner 实际安装的引擎候选清单",
)
async def get_admin_engine_catalog(
    _admin: Annotated[CurrentUser, Depends(get_current_admin)],
    request: Request,
    response: Response,
) -> EngineCatalogResponse:
    response.headers["Cache-Control"] = "no-store"
    reader = require_service(
        get_services(request).engine_catalog_reader, "engine catalog"
    )
    try:
        return await reader()
    except MediaRunnerClientError as exc:
        raise AppError(
            status=503,
            code="service_unavailable",
            title="Engine catalog unavailable",
            detail="引擎候选清单暂时不可用，请稍后重试。",
        ) from exc


@router.get(
    "",
    operation_id="getAdminProviderRuntime",
    response_model=ProviderRuntimeListResponse,
    summary="读取已开放平台的脱敏运行诊断",
)
async def get_admin_provider_runtime(
    _admin: Annotated[CurrentUser, Depends(get_current_admin)],
    statuses: Annotated[tuple[ProviderStatusView, ...], Depends(get_provider_statuses)],
    request: Request,
    response: Response,
) -> ProviderRuntimeListResponse:
    """仅元数据快照，不登录、不导出会话、不解析或下载媒体。"""
    response.headers["Cache-Control"] = "no-store"
    return ProviderRuntimeListResponse(
        items=tuple(ProviderRuntimeResponse.from_view(item) for item in statuses)
    )
