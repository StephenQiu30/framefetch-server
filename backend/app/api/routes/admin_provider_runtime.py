from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import (
    get_current_admin,
    get_services,
    require_service,
)
from app.api.responses import ApiResponseRoute
from app.core.errors import AppError
from app.integrations.media_runner_models import MediaRunnerClientError
from app.schemas.engine_catalog import EngineCatalogResponse
from app.services.auth.models import CurrentUser

router = APIRouter(
    route_class=ApiResponseRoute, prefix="/admin/provider-runtime", tags=["admin"]
)


@router.get(
    "/engine-catalog",
    operation_id="getAdminEngineCatalog",
    response_model=EngineCatalogResponse,
    summary="读取媒体 Runner 实际安装的引擎候选清单",
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
