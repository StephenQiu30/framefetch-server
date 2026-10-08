from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import StrictModel
from app.services.workspace_documents.rules import (
    MAX_DOCUMENT_BYTES,
    WorkspaceDocument,
    WorkspaceDocumentSummary,
)


class WorkspaceDocumentSummaryResponse(StrictModel):
    path: str = Field(description="相对 workspace/content 的 Markdown 路径。")
    title: str = Field(description="文档一级标题；没有标题时为文件名。")
    section: str = Field(description="所在目录，如 prd、design、plan；根目录为空。")

    @classmethod
    def from_summary(
        cls, summary: WorkspaceDocumentSummary
    ) -> WorkspaceDocumentSummaryResponse:
        return cls(path=summary.path, title=summary.title, section=summary.section)


class WorkspaceDocumentListResponse(StrictModel):
    items: list[WorkspaceDocumentSummaryResponse]


class WorkspaceDocumentResponse(StrictModel):
    path: str
    title: str
    content: str = Field(description="Markdown 原文。")
    sha256: str = Field(description="原文 SHA-256，保存时作为 base_sha256 提交。")
    updated_at: datetime

    @classmethod
    def from_document(cls, document: WorkspaceDocument) -> WorkspaceDocumentResponse:
        return cls(
            path=document.path,
            title=document.title,
            content=document.content,
            sha256=document.sha256,
            updated_at=document.updated_at,
        )


class UpdateWorkspaceDocumentRequest(StrictModel):
    content: str = Field(
        max_length=MAX_DOCUMENT_BYTES, description="新的 Markdown 原文。"
    )
    base_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="编辑开始时读取到的原文 SHA-256；不一致时返回 409。",
    )
