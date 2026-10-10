from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.admission import RateLimitAdmission
from app.api.deps import (
    IdempotencyKey,
    get_current_user,
    get_media_import_use_cases,
    get_runtime_settings,
)
from app.api.responses import ApiResponseRoute
from app.api.upload_signing import use_local_browser_upload_endpoint
from app.core.runtime import MediaImportUseCases
from app.schemas.media_imports import (
    CompleteMediaImportRequest,
    MediaImportRequest,
    MediaImportResponse,
    MediaUploadSessionResponse,
)
from app.services.auth.models import CurrentUser
from app.services.imports.models import CompletedUploadPart
from app.services.imports.rules.enums import ContentKind, ImportSourceFormat

router = APIRouter(
    route_class=ApiResponseRoute, prefix="/media-imports", tags=["media-imports"]
)
User = Annotated[CurrentUser, Depends(get_current_user)]
UseCases = Annotated[MediaImportUseCases, Depends(get_media_import_use_cases)]


@router.post(
    "",
    operation_id="createMediaImport",
    dependencies=[Depends(RateLimitAdmission("media_import"))],
    response_model=MediaImportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建本地视频导入",
)
async def create_media_import(
    body: MediaImportRequest,
    idempotency_key: IdempotencyKey,
    response: Response,
    user: User,
    use_cases: UseCases,
) -> MediaImportResponse:
    """创建只接受 MP4 的浏览器上传资源，不接收任意存储参数。"""
    view = await use_cases.create_resource(
        owner_hash=user.owner_hash,
        idempotency_key=idempotency_key,
        content_kind=ContentKind.VIDEO,
        source_format=ImportSourceFormat.MP4,
        file_name=body.file_name,
        declared_size_bytes=body.declared_size_bytes,
        declared_sha256=body.declared_sha256,
        rights_accepted=body.rights_accepted,
        declared_origin=body.declared_origin,
        remove_watermark=body.remove_watermark,
        quota=user.admission_quota,
    )
    response.headers["Location"] = f"/api/media-imports/{view.id}"
    response.headers["Cache-Control"] = "no-store"
    return MediaImportResponse.from_view(view)


@router.get(
    "/{resource_id}",
    operation_id="getMediaImport",
    response_model=MediaImportResponse,
    summary="查询本地视频导入",
)
async def get_media_import(
    resource_id: UUID,
    response: Response,
    user: User,
    use_cases: UseCases,
) -> MediaImportResponse:
    view = await use_cases.get_import(resource_id, user.owner_hash, ContentKind.VIDEO)
    response.headers["Cache-Control"] = "no-store"
    return MediaImportResponse.from_view(view)


@router.post(
    "/{resource_id}/upload-sessions",
    operation_id="createMediaUploadSession",
    dependencies=[Depends(RateLimitAdmission("media_import_upload"))],
    response_model=MediaUploadSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建或刷新视频上传会话",
)
async def create_media_upload_session(
    resource_id: UUID,
    request: Request,
    response: Response,
    user: User,
    use_cases: UseCases,
) -> MediaUploadSessionResponse:
    view = await use_cases.create_upload_session(
        resource_id,
        user.owner_hash,
        ContentKind.VIDEO,
        use_local_browser_endpoint=use_local_browser_upload_endpoint(
            request, get_runtime_settings(request)
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    return MediaUploadSessionResponse.from_view(view)


@router.post(
    "/{resource_id}/complete",
    operation_id="completeMediaImport",
    dependencies=[Depends(RateLimitAdmission("media_import_upload"))],
    response_model=MediaImportResponse,
    summary="完成视频上传并触发验证",
)
async def complete_media_import(
    resource_id: UUID,
    body: CompleteMediaImportRequest,
    response: Response,
    user: User,
    use_cases: UseCases,
) -> MediaImportResponse:
    view = await use_cases.complete_upload(
        resource_id,
        user.owner_hash,
        ContentKind.VIDEO,
        tuple(CompletedUploadPart(part.part_number, part.etag) for part in body.parts),
    )
    response.headers["Cache-Control"] = "no-store"
    return MediaImportResponse.from_view(view)
