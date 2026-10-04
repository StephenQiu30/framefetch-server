"""Owner-scoped browser upload endpoints for screenplay documents."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.api.admission import RateLimitAdmission
from app.api.deps import (
    IdempotencyKey,
    get_current_user,
    get_document_import_use_cases,
    get_runtime_settings,
)
from app.api.responses import ApiResponseRoute
from app.api.upload_signing import use_local_browser_upload_endpoint
from app.core.runtime import DocumentImportUseCases
from app.schemas.documents import (
    CompleteDocumentImportRequest,
    DocumentDetailResponse,
    DocumentImportRequest,
    DocumentImportResponse,
    DocumentPageResponse,
    DocumentUploadSessionResponse,
)
from app.services.auth.models import CurrentUser
from app.services.imports.models import CompletedUploadPart
from app.services.imports.rules.enums import ContentKind, ImportSourceFormat

router = APIRouter(
    route_class=ApiResponseRoute, prefix="/documents", tags=["documents"]
)
User = Annotated[CurrentUser, Depends(get_current_user)]
UseCases = Annotated[DocumentImportUseCases, Depends(get_document_import_use_cases)]


@router.post(
    "",
    operation_id="createDocumentImport",
    dependencies=[Depends(RateLimitAdmission("document_import"))],
    response_model=DocumentImportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建文档导入",
)
async def create_document_import(
    body: DocumentImportRequest,
    idempotency_key: IdempotencyKey,
    response: Response,
    user: User,
    use_cases: UseCases,
) -> DocumentImportResponse:
    view = await use_cases.create_resource(
        owner_hash=user.owner_hash,
        idempotency_key=idempotency_key,
        content_kind=ContentKind.SCREENPLAY,
        source_format=ImportSourceFormat(body.source_format),
        file_name=body.file_name,
        declared_size_bytes=body.declared_size_bytes,
        declared_sha256=body.declared_sha256,
        rights_accepted=body.rights_accepted,
        quota=user.admission_quota,
    )
    response.headers["Location"] = f"/api/documents/{view.id}"
    response.headers["Cache-Control"] = "no-store"
    return DocumentImportResponse.from_view(view)


@router.get(
    "",
    operation_id="listDocuments",
    response_model=DocumentPageResponse,
    summary="查询文档列表",
)
async def list_documents(
    user: User,
    use_cases: UseCases,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> DocumentPageResponse:
    view = await use_cases.list_documents(
        user.owner_hash, page=page, page_size=page_size
    )
    return DocumentPageResponse.from_view(view)


@router.get(
    "/{document_id}",
    operation_id="getDocumentImport",
    response_model=DocumentDetailResponse,
    summary="查询文档导入",
)
async def get_document_import(
    document_id: UUID,
    response: Response,
    user: User,
    use_cases: UseCases,
) -> DocumentDetailResponse:
    await use_cases.get_import(document_id, user.owner_hash, ContentKind.SCREENPLAY)
    view = await use_cases.get_document(document_id, user.owner_hash)
    response.headers["Cache-Control"] = "no-store"
    return DocumentDetailResponse.from_view(view)


@router.delete(
    "/{document_id}",
    operation_id="deleteDocument",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除文档及其制品",
)
async def delete_document(
    document_id: UUID,
    user: User,
    use_cases: UseCases,
) -> Response:
    await use_cases.delete_document(document_id, user.owner_hash)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{document_id}/upload-sessions",
    operation_id="createDocumentUploadSession",
    dependencies=[Depends(RateLimitAdmission("document_import_upload"))],
    response_model=DocumentUploadSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建或刷新文档上传会话",
)
async def create_document_upload_session(
    document_id: UUID,
    request: Request,
    response: Response,
    user: User,
    use_cases: UseCases,
) -> DocumentUploadSessionResponse:
    view = await use_cases.create_upload_session(
        document_id,
        user.owner_hash,
        ContentKind.SCREENPLAY,
        use_local_browser_endpoint=use_local_browser_upload_endpoint(
            request, get_runtime_settings(request)
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    return DocumentUploadSessionResponse.from_view(view)


@router.post(
    "/{document_id}/complete",
    operation_id="completeDocumentImport",
    dependencies=[Depends(RateLimitAdmission("document_import_upload"))],
    response_model=DocumentImportResponse,
    summary="完成文档上传并触发验证",
)
async def complete_document_import(
    document_id: UUID,
    body: CompleteDocumentImportRequest,
    response: Response,
    user: User,
    use_cases: UseCases,
) -> DocumentImportResponse:
    view = await use_cases.complete_upload(
        document_id,
        user.owner_hash,
        ContentKind.SCREENPLAY,
        tuple(CompletedUploadPart(part.part_number, part.etag) for part in body.parts),
    )
    response.headers["Cache-Control"] = "no-store"
    return DocumentImportResponse.from_view(view)


@router.post(
    "/{document_id}/cancel",
    operation_id="cancelDocumentImport",
    response_model=DocumentImportResponse,
    summary="取消文档导入",
)
async def cancel_document_import(
    document_id: UUID,
    user: User,
    use_cases: UseCases,
) -> DocumentImportResponse:
    view = await use_cases.cancel_import(
        document_id, user.owner_hash, ContentKind.SCREENPLAY
    )
    return DocumentImportResponse.from_view(view)
