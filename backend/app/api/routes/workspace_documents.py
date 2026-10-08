from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_admin, get_workspace_store
from app.api.responses import ApiResponseRoute
from app.integrations.workspace_content import WorkspaceContentStore
from app.schemas.workspace_documents import (
    UpdateWorkspaceDocumentRequest,
    WorkspaceDocumentListResponse,
    WorkspaceDocumentResponse,
    WorkspaceDocumentSummaryResponse,
)
from app.services.auth.models import CurrentUser

router = APIRouter(
    route_class=ApiResponseRoute, prefix="/workspace", tags=["workspace"]
)
Store = Annotated[WorkspaceContentStore, Depends(get_workspace_store)]
Admin = Annotated[CurrentUser, Depends(get_current_admin)]
DocumentPath = Annotated[
    str,
    Query(
        min_length=1,
        max_length=512,
        description="相对 workspace/content 的 Markdown 路径。",
    ),
]


@router.get(
    "/documents",
    operation_id="listWorkspaceDocuments",
    response_model=WorkspaceDocumentListResponse,
    summary="列出工作区文档",
)
async def list_workspace_documents(store: Store) -> WorkspaceDocumentListResponse:
    """返回 workspace/content 下全部 Markdown 文档；公开只读。"""
    summaries = await store.summaries()
    return WorkspaceDocumentListResponse(
        items=[WorkspaceDocumentSummaryResponse.from_summary(s) for s in summaries]
    )


@router.get(
    "/document",
    operation_id="getWorkspaceDocument",
    response_model=WorkspaceDocumentResponse,
    summary="读取工作区文档",
)
async def get_workspace_document(
    store: Store, path: DocumentPath
) -> WorkspaceDocumentResponse:
    """返回文档原文与 SHA-256；公开只读。"""
    return WorkspaceDocumentResponse.from_document(await store.read(path))


@router.put(
    "/document",
    operation_id="updateWorkspaceDocument",
    response_model=WorkspaceDocumentResponse,
    summary="保存工作区文档",
)
async def update_workspace_document(
    store: Store,
    admin: Admin,
    path: DocumentPath,
    body: UpdateWorkspaceDocumentRequest,
) -> WorkspaceDocumentResponse:
    """管理员覆盖已有文档；base_sha256 与当前原文不一致时返回 409，不新建或删除文件。"""
    document = await store.write(path, body.content, body.base_sha256)
    return WorkspaceDocumentResponse.from_document(document)
