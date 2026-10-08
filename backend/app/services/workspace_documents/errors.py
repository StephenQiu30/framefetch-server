from __future__ import annotations

from enum import StrEnum


class WorkspaceDocumentErrorCode(StrEnum):
    INVALID_PATH = "invalid_request"
    NOT_FOUND = "workspace_document_not_found"
    CONFLICT = "workspace_document_conflict"
    TOO_LARGE = "request_too_large"
    UNAVAILABLE = "workspace_unavailable"


class WorkspaceDocumentError(RuntimeError):
    def __init__(self, code: WorkspaceDocumentErrorCode) -> None:
        self.code = code
        super().__init__(code.value)
