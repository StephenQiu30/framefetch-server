from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.admission import RateLimitAdmission
from app.api.deps import IdempotencyKey, get_current_user, get_download_use_cases
from app.api.responses import ApiResponseRoute
from app.core.runtime import DownloadUseCases
from app.schemas.inspections import (
    InspectionRequest,
    InspectionResponse,
    PublicUrlInspectionSource,
)
from app.services.auth.models import CurrentUser

router = APIRouter(
    route_class=ApiResponseRoute, prefix="/inspections", tags=["inspections"]
)
User = Annotated[CurrentUser, Depends(get_current_user)]
UseCases = Annotated[DownloadUseCases, Depends(get_download_use_cases)]


@router.post(
    "",
    operation_id="inspectMedia",
    dependencies=[Depends(RateLimitAdmission("inspect"))],
    response_model=InspectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="解析媒体信息",
)
async def inspect_media(
    body: InspectionRequest,
    idempotency_key: IdempotencyKey,
    user: User,
    use_cases: UseCases,
    response: Response,
) -> InspectionResponse:
    """校验公开媒体地址并返回可供选择的语义下载格式。"""
    if isinstance(body.source, PublicUrlInspectionSource):
        view = await use_cases.inspect_media(
            body.source.url,
            user.owner_hash,
            idempotency_key,
        )
    else:
        view = await use_cases.inspect_discovered_item(
            body.source.discovery_id,
            body.source.item_ref,
            user.owner_hash,
            idempotency_key,
        )
    response.headers["Location"] = f"/api/inspections/{view.id}"
    return InspectionResponse.from_view(view)


@router.get(
    "/{inspection_id}/thumbnail",
    operation_id="getInspectionThumbnail",
    response_class=Response,
    responses={
        200: {
            "description": "Private persisted media thumbnail",
            "content": {
                "image/avif": {"schema": {"type": "string", "format": "binary"}},
                "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
                "image/png": {"schema": {"type": "string", "format": "binary"}},
                "image/webp": {"schema": {"type": "string", "format": "binary"}},
            },
        }
    },
    summary="读取持久化媒体封面",
)
async def get_inspection_thumbnail(
    inspection_id: UUID,
    user: User,
    use_cases: UseCases,
) -> Response:
    """读取当前用户拥有且存储在私有对象存储中的媒体封面。"""
    thumbnail = await use_cases.get_thumbnail(inspection_id, user.owner_hash)
    return Response(
        content=thumbnail.content,
        media_type=thumbnail.content_type,
        headers={
            "Cache-Control": "private, max-age=3600",
            "ETag": f'"{thumbnail.sha256}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/{inspection_id}",
    operation_id="getInspection",
    response_model=InspectionResponse,
    summary="查询媒体解析结果",
)
async def get_inspection(
    inspection_id: UUID,
    user: User,
    use_cases: UseCases,
) -> InspectionResponse:
    """查询当前登录用户拥有的媒体解析结果。"""
    view = await use_cases.get_inspection(inspection_id, user.owner_hash)
    return InspectionResponse.from_view(view)
