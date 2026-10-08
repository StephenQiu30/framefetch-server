"""RFC 9457 response mapping."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from http import HTTPStatus
from math import ceil
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.schemas.response import ErrorResponse
from app.services.ai_model_catalog import ModelCatalogUnavailable
from app.services.ai_provider_models import AiProviderError, AiProviderErrorCode
from app.services.analysis.errors import (
    AnalysisApplicationError,
    AnalysisApplicationErrorCode,
)
from app.services.auth.errors import AuthError, AuthErrorCode, SessionRotationConflict
from app.services.downloads.errors import ApplicationError, ApplicationErrorCode
from app.services.imports.errors import (
    ImportApplicationError,
    ImportApplicationErrorCode,
)
from app.services.provider_catalog import ProviderCatalogError, ProviderCatalogErrorCode
from app.services.quotas import QuotaExceeded
from app.services.storage_files.errors import StorageFileError, StorageFileErrorCode
from app.services.workspace_documents.errors import (
    WorkspaceDocumentError,
    WorkspaceDocumentErrorCode,
)

logger = logging.getLogger(__name__)

_ERRORS: dict[ApplicationErrorCode, tuple[int, str, str]] = {
    ApplicationErrorCode.ARTICLE_ACCESS_RESTRICTED: (
        403,
        "Article access restricted",
        "The article requires a challenge, authentication, follow, or payment "
        "and cannot be discovered safely.",
    ),
    ApplicationErrorCode.ARTICLE_DISCOVERY_FAILED: (
        502,
        "Article discovery failed",
        "The public article could not be parsed within the safe discovery limits.",
    ),
    ApplicationErrorCode.DOWNLOAD_NOT_READY: (
        409,
        "Download not ready",
        "The download is not ready for file delivery.",
    ),
    ApplicationErrorCode.DURATION_LIMIT_EXCEEDED: (
        422,
        "Duration limit exceeded",
        "The media exceeds the configured duration limit.",
    ),
    ApplicationErrorCode.FORMAT_UNAVAILABLE: (
        422,
        "Format unavailable",
        "No supported semantic download format is available.",
    ),
    ApplicationErrorCode.IDEMPOTENCY_CONFLICT: (
        409,
        "Idempotency conflict",
        "The idempotency key was already used for another request.",
    ),
    ApplicationErrorCode.INTERNAL_ERROR: (
        500,
        "Internal error",
        "The request could not be completed.",
    ),
    ApplicationErrorCode.INVALID_REQUEST: (
        422,
        "Invalid request",
        "The request parameters are invalid.",
    ),
    ApplicationErrorCode.INVALID_STATE: (
        409,
        "Invalid state",
        "The resource cannot perform this operation in its current state.",
    ),
    ApplicationErrorCode.INVALID_URL: (
        422,
        "Invalid URL",
        "The submitted media URL is not allowed.",
    ),
    ApplicationErrorCode.NOT_FOUND: (
        404,
        "Not found",
        "The requested resource was not found.",
    ),
    ApplicationErrorCode.NETWORK_BLOCKED: (
        502,
        "Network blocked",
        "The provider blocked the configured network route.",
    ),
    ApplicationErrorCode.CHALLENGE: (
        502,
        "Platform challenge",
        "The provider requires a client challenge.",
    ),
    ApplicationErrorCode.LOGIN_REQUIRED: (
        403,
        "Platform login required",
        "This media requires a platform login.",
    ),
    ApplicationErrorCode.CONTENT_UNAVAILABLE: (
        422,
        "Content unavailable",
        "The requested content is unavailable.",
    ),
    ApplicationErrorCode.IDENTITY_UNAVAILABLE: (
        503,
        "Platform identity unavailable",
        "The required platform identity is unavailable.",
    ),
    ApplicationErrorCode.RATE_LIMITED: (
        429,
        "Platform rate limited",
        "The provider rate limit was reached. Try again after the indicated delay.",
    ),
    ApplicationErrorCode.CONTEXT_CHANGED: (
        409,
        "Execution context changed",
        "The media execution context changed. Resolve again and confirm the format.",
    ),
    ApplicationErrorCode.CONTENT_PROTECTED: (
        422,
        "Protected content",
        "Encrypted media cannot be downloaded. Import an existing clear file.",
    ),
    ApplicationErrorCode.EXTRACTOR_BROKEN: (
        502,
        "Extractor unavailable",
        "The extractor could not resolve this media.",
    ),
    ApplicationErrorCode.TRANSIENT: (
        503,
        "Temporary failure",
        "The media operation failed temporarily. Try again later.",
    ),
    ApplicationErrorCode.INVALID_INPUT: (
        422,
        "Invalid media input",
        "The requested source is not supported.",
    ),
    ApplicationErrorCode.RUNTIME_UNAVAILABLE: (
        503,
        "Media runtime unavailable",
        "The media runtime is temporarily unavailable.",
    ),
    ApplicationErrorCode.RESOURCE_EXPIRED: (
        404,
        "Not found",
        "The requested resource was not found.",
    ),
    ApplicationErrorCode.STORAGE_UNAVAILABLE: (
        503,
        "Storage unavailable",
        "The media preview is temporarily unavailable.",
    ),
}

_ANALYSIS_ERRORS: dict[AnalysisApplicationErrorCode, tuple[int, str, str]] = {
    AnalysisApplicationErrorCode.ALREADY_ACTIVE: (
        409,
        "Analysis already active",
        "The analysis already has an active execution run.",
    ),
    AnalysisApplicationErrorCode.ARTIFACT_UNAVAILABLE: (
        409,
        "Analysis artifact unavailable",
        "The original video artifact is no longer available for analysis.",
    ),
    AnalysisApplicationErrorCode.ARTIFACT_NOT_READY: (
        409,
        "Artifact not ready",
        "The download artifact is not ready for analysis.",
    ),
    AnalysisApplicationErrorCode.IDEMPOTENCY_CONFLICT: (
        409,
        "Idempotency conflict",
        "The idempotency key was already used for another request.",
    ),
    AnalysisApplicationErrorCode.INTERNAL_ERROR: (
        500,
        "Internal error",
        "The request could not be completed.",
    ),
    AnalysisApplicationErrorCode.INVALID_MODEL_OUTPUT: (
        502,
        "Invalid model output",
        "The analysis provider returned an invalid result.",
    ),
    AnalysisApplicationErrorCode.INVALID_REQUEST: (
        422,
        "Invalid request",
        "The request parameters are invalid.",
    ),
    AnalysisApplicationErrorCode.INVALID_STATE: (
        409,
        "Invalid state",
        "The analysis cannot perform this operation in its current state.",
    ),
    AnalysisApplicationErrorCode.NOT_FOUND: (
        404,
        "Not found",
        "The requested resource was not found.",
    ),
    AnalysisApplicationErrorCode.PROVIDER_FAILURE: (
        502,
        "Analysis provider failure",
        "The analysis provider could not complete the request.",
    ),
    AnalysisApplicationErrorCode.REPORT_NOT_READY: (
        409,
        "Analysis report not ready",
        "The analysis report has not finished publishing.",
    ),
    AnalysisApplicationErrorCode.REPORT_UNAVAILABLE: (
        503,
        "Analysis report unavailable",
        "The published analysis report could not be verified.",
    ),
    AnalysisApplicationErrorCode.RETRY_LIMITED: (
        429,
        "Analysis retry limited",
        "The analysis retry limit was reached. Try again later.",
    ),
    AnalysisApplicationErrorCode.SKILL_OUTDATED: (
        409,
        "Analysis skill outdated",
        "The saved skill has changed. Create a new analysis task "
        "with the current skill.",
    ),
    AnalysisApplicationErrorCode.SERVICE_UNAVAILABLE: (
        503,
        "Analysis unavailable",
        "Video analysis is not enabled for this deployment.",
    ),
}

_IMPORT_ERRORS: dict[ImportApplicationErrorCode, tuple[int, str, str]] = {
    ImportApplicationErrorCode.DISABLED: (
        503,
        "Media import unavailable",
        "Local media import is not enabled for this deployment.",
    ),
    ImportApplicationErrorCode.IDEMPOTENCY_CONFLICT: (
        409,
        "Idempotency conflict",
        "The idempotency key was already used for another request.",
    ),
    ImportApplicationErrorCode.INTERNAL_ERROR: (
        500,
        "Internal error",
        "The import request could not be completed.",
    ),
    ImportApplicationErrorCode.INVALID_REQUEST: (
        422,
        "Invalid import request",
        "The local file declaration is invalid.",
    ),
    ImportApplicationErrorCode.INVALID_STATE: (
        409,
        "Invalid import state",
        "The import cannot perform this operation in its current state.",
    ),
    ImportApplicationErrorCode.NOT_FOUND: (
        404,
        "Import not found",
        "The requested import resource was not found.",
    ),
    ImportApplicationErrorCode.SIZE_MISMATCH: (
        422,
        "Import size mismatch",
        "The uploaded object size differs from the declared file size.",
    ),
    ImportApplicationErrorCode.STORAGE_UNAVAILABLE: (
        503,
        "Import storage unavailable",
        "The upload storage is temporarily unavailable.",
    ),
    ImportApplicationErrorCode.UPLOAD_INCOMPLETE: (
        422,
        "Upload incomplete",
        "The multipart upload is incomplete or invalid.",
    ),
    ImportApplicationErrorCode.UPLOAD_SESSION_EXPIRED: (
        409,
        "Upload session expired",
        "Create a new upload session and retry the upload.",
    ),
}

_AUTH_ERRORS: dict[AuthErrorCode, tuple[int, str, str]] = {
    AuthErrorCode.ADMIN_BOOTSTRAP_REQUIRED: (
        403,
        "Administrator bootstrap required",
        "This reserved administrator account requires bootstrap authorization.",
    ),
    AuthErrorCode.EMAIL_ALREADY_REGISTERED: (
        409,
        "Email already registered",
        "An account with this email already exists.",
    ),
    AuthErrorCode.INVALID_CREDENTIALS: (
        401,
        "Invalid credentials",
        "The email or password is incorrect.",
    ),
    AuthErrorCode.USERNAME_ALREADY_REGISTERED: (
        409,
        "Username already registered",
        "This username is already in use.",
    ),
    AuthErrorCode.INVALID_USERNAME: (
        422,
        "Invalid username",
        "The username format is invalid.",
    ),
    AuthErrorCode.FORBIDDEN: (
        403,
        "Forbidden",
        "Administrator access is required.",
    ),
    AuthErrorCode.USER_NOT_FOUND: (
        404,
        "User not found",
        "The requested user does not exist.",
    ),
    AuthErrorCode.SELF_ADMIN_CHANGE: (
        409,
        "Self administration conflict",
        "Administrators cannot disable or delete their own account.",
    ),
    AuthErrorCode.LAST_ADMIN_CHANGE: (
        409,
        "Last administrator required",
        "Keep at least one active administrator before changing this account.",
    ),
    AuthErrorCode.INVALID_VERIFICATION_CODE: (
        400,
        "Invalid verification code",
        "Request a new code or check the email and code.",
    ),
    AuthErrorCode.VERIFICATION_RATE_LIMITED: (
        429,
        "Please wait",
        "Wait 60 seconds before requesting another code.",
    ),
    AuthErrorCode.EMAIL_UNAVAILABLE: (
        503,
        "Email unavailable",
        "Registration email is not configured.",
    ),
    AuthErrorCode.EMAIL_SEND_FAILED: (
        503,
        "Email send failed",
        "Email could not be confirmed. Please request a new code later.",
    ),
    AuthErrorCode.UNAUTHENTICATED: (
        401,
        "Authentication required",
        "Sign in to continue.",
    ),
}

_STORAGE_FILE_ERRORS: dict[StorageFileErrorCode, tuple[int, str, str]] = {
    StorageFileErrorCode.NOT_FOUND: (
        404,
        "File not found",
        "The requested persistent file was not found.",
    ),
    StorageFileErrorCode.IN_USE: (
        409,
        "File is in use",
        "The file is currently used by an active analysis and cannot be deleted.",
    ),
    StorageFileErrorCode.STORAGE_UNAVAILABLE: (
        503,
        "Storage unavailable",
        "The file could not be deleted because storage is temporarily unavailable.",
    ),
}


def application_error(error: ApplicationError) -> AppError:
    status, title, detail = _ERRORS[error.code]
    return AppError(
        status=status,
        code=error.code.value,
        title=title,
        detail=detail,
        headers=(
            {
                "Retry-After": str(
                    max(1, ceil((error.retry_at - datetime.now(UTC)).total_seconds()))
                )
            }
            if error.retry_at is not None
            else None
        ),
    )


def analysis_application_error(error: AnalysisApplicationError) -> AppError:
    status, title, detail = _ANALYSIS_ERRORS[error.code]
    return AppError(
        status=status,
        code=error.code.value,
        title=title,
        detail=detail,
    )


def import_application_error(error: ImportApplicationError) -> AppError:
    status, title, detail = _IMPORT_ERRORS[error.code]
    return AppError(
        status=status,
        code=error.code.value,
        title=title,
        detail=detail,
    )


def auth_application_error(error: AuthError) -> AppError:
    status, title, detail = _AUTH_ERRORS[error.code]
    return AppError(status=status, code=error.code.value, title=title, detail=detail)


_WORKSPACE_DOCUMENT_ERRORS: dict[WorkspaceDocumentErrorCode, tuple[int, str, str]] = {
    WorkspaceDocumentErrorCode.INVALID_PATH: (
        400,
        "Invalid document path",
        "The document path must be a relative Markdown path inside the workspace.",
    ),
    WorkspaceDocumentErrorCode.NOT_FOUND: (
        404,
        "Document not found",
        "The requested workspace document does not exist.",
    ),
    WorkspaceDocumentErrorCode.CONFLICT: (
        409,
        "Document changed",
        "The document was modified after it was loaded. Reload it before saving.",
    ),
    WorkspaceDocumentErrorCode.TOO_LARGE: (
        413,
        "Document too large",
        "The document exceeds the workspace size limit.",
    ),
    WorkspaceDocumentErrorCode.UNAVAILABLE: (
        503,
        "Workspace unavailable",
        "The workspace content directory is not configured on this deployment.",
    ),
}


def workspace_document_error(error: WorkspaceDocumentError) -> AppError:
    status, title, detail = _WORKSPACE_DOCUMENT_ERRORS[error.code]
    return AppError(status=status, code=error.code.value, title=title, detail=detail)


def storage_file_error(error: StorageFileError) -> AppError:
    status, title, detail = _STORAGE_FILE_ERRORS[error.code]
    return AppError(status=status, code=error.code.value, title=title, detail=detail)


async def app_error_handler(request: Request, error: Exception) -> JSONResponse:
    return error_response(request, cast(AppError, error))


async def validation_error_handler(request: Request, _error: Exception) -> JSONResponse:
    return error_response(
        request,
        AppError(
            status=422,
            code=ErrorCode.INVALID_REQUEST,
            title="Invalid request",
            detail="The request parameters are invalid.",
        ),
    )


def error_response(request: Request, error: AppError) -> JSONResponse:
    if request.url.path.startswith("/api/app/v1/"):
        # The independently versioned native API retains its published contract.
        return JSONResponse(
            status_code=error.status,
            media_type="application/problem+json",
            headers=error.headers,
            content={
                "type": f"urn:framefetch-server:error:{error.code}",
                "title": error.title,
                "status": error.status,
                "detail": error.detail,
                "code": error.code,
                "instance": request.url.path,
            },
        )
    return JSONResponse(
        status_code=error.status,
        headers=error.headers,
        content=ErrorResponse(
            code=ErrorCode(error.code), message=error.detail, data=None
        ).model_dump(mode="json"),
    )


async def quota_error_handler(request: Request, error: Exception) -> JSONResponse:
    quota = cast(QuotaExceeded, error)
    details = {
        "active_task_quota_exceeded": "Wait for active tasks to finish or cancel them.",
        "daily_task_quota_exceeded": "The rolling 24-hour task budget is exhausted.",
        "daily_byte_quota_exceeded": "The rolling 24-hour byte budget is exhausted.",
        "analysis_budget_exceeded": "The rolling 24-hour analysis budget is exhausted.",
        "storage_quota_exceeded": (
            "Delete retained files or finish active tasks to free space."
        ),
    }
    return await app_error_handler(
        request,
        AppError(
            status=429,
            code=quota.code,
            title="Resource budget exceeded",
            detail=details[quota.code],
            headers={"Retry-After": str(quota.retry_after)},
        ),
    )


def _provider_error(error: AiProviderError) -> AppError:
    mapping = {
        AiProviderErrorCode.FORBIDDEN: (
            403,
            "Forbidden",
            "Administrator access is required.",
        ),
        AiProviderErrorCode.INVALID_PROFILE: (
            422,
            "Invalid AI Provider profile",
            "The AI Provider profile is invalid or incomplete.",
        ),
        AiProviderErrorCode.CONFLICT: (
            409,
            "AI Provider conflict",
            "An AI Provider profile with this key already exists.",
        ),
        AiProviderErrorCode.NOT_FOUND: (
            404,
            "AI Provider not found",
            "The requested AI Provider profile does not exist.",
        ),
        AiProviderErrorCode.ACTIVE_DELETE: (
            409,
            "Active AI Provider cannot be deleted",
            "Activate another AI Provider before deleting this profile.",
        ),
        AiProviderErrorCode.RESERVED_MUTATION: (
            409,
            "Built-in AI Provider is protected",
            "The local Codex fallback only allows display name and model changes.",
        ),
    }
    status_code, title, detail = mapping[error.code]
    return AppError(
        status=status_code,
        code=error.code.value,
        title=title,
        detail=detail,
    )


def _catalog_error(error: ProviderCatalogError) -> AppError:
    mapping = {
        ProviderCatalogErrorCode.FORBIDDEN: (
            403,
            "Forbidden",
            "Administrator access is required.",
        ),
        ProviderCatalogErrorCode.INVALID_ENTRY: (
            422,
            "Invalid Provider catalog entry",
            "The Provider catalog entry is invalid.",
        ),
        ProviderCatalogErrorCode.CONFLICT: (
            409,
            "Provider catalog conflict",
            "A Provider catalog entry with this key already exists.",
        ),
        ProviderCatalogErrorCode.NOT_FOUND: (
            404,
            "Provider catalog entry not found",
            "The requested Provider catalog entry does not exist.",
        ),
    }
    status_code, title, detail = mapping[error.code]
    return AppError(
        status=status_code,
        code=error.code.value,
        title=title,
        detail=detail,
    )


async def business_error_handler(request: Request, error: Exception) -> JSONResponse:
    if isinstance(error, SessionRotationConflict):
        mapped = AppError(
            status=409,
            code=ErrorCode.REFRESH_IN_PROGRESS,
            title="Session refresh in progress",
            detail="Another request has already refreshed this session.",
        )
    elif isinstance(error, ModelCatalogUnavailable):
        mapped = AppError(
            status=503,
            code=ErrorCode.AI_MODEL_CATALOG_UNAVAILABLE,
            title="Model catalog unavailable",
            detail="The model catalog is temporarily unavailable.",
        )
    elif isinstance(error, ApplicationError):
        mapped = application_error(error)
    elif isinstance(error, AnalysisApplicationError):
        mapped = analysis_application_error(error)
    elif isinstance(error, ImportApplicationError):
        mapped = import_application_error(error)
    elif isinstance(error, AuthError):
        mapped = auth_application_error(error)
    elif isinstance(error, AiProviderError):
        mapped = _provider_error(error)
    elif isinstance(error, ProviderCatalogError):
        mapped = _catalog_error(error)
    elif isinstance(error, StorageFileError):
        mapped = storage_file_error(error)
    elif isinstance(error, WorkspaceDocumentError):
        mapped = workspace_document_error(error)
    else:
        return await unexpected_error_handler(request, error)
    return error_response(request, mapped)


async def http_error_handler(request: Request, error: Exception) -> JSONResponse:
    exception = cast(HTTPException, error)
    code = {
        400: ErrorCode.INVALID_REQUEST,
        401: ErrorCode.UNAUTHENTICATED,
        403: ErrorCode.FORBIDDEN,
        404: ErrorCode.NOT_FOUND,
        405: ErrorCode.METHOD_NOT_ALLOWED,
        413: ErrorCode.REQUEST_TOO_LARGE,
        422: ErrorCode.INVALID_REQUEST,
        429: ErrorCode.RATE_LIMITED,
    }.get(exception.status_code, ErrorCode.HTTP_ERROR)
    return error_response(
        request,
        AppError(
            status=exception.status_code,
            code=code,
            title="Request failed",
            detail=(
                HTTPStatus(exception.status_code).phrase
                if exception.status_code in HTTPStatus._value2member_map_
                else "Request failed"
            ),
            headers=dict(exception.headers) if exception.headers else None,
        ),
    )


async def unexpected_error_handler(request: Request, error: Exception) -> JSONResponse:
    logger.error("Unhandled API exception: %s", type(error).__name__)
    return error_response(
        request,
        AppError(
            status=500,
            code=ErrorCode.INTERNAL_ERROR,
            title="Internal error",
            detail="An internal error occurred. Please try again later.",
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    for error_type in (
        ApplicationError,
        AnalysisApplicationError,
        ImportApplicationError,
        AuthError,
        AiProviderError,
        ProviderCatalogError,
        StorageFileError,
        WorkspaceDocumentError,
        SessionRotationConflict,
        ModelCatalogUnavailable,
    ):
        app.add_exception_handler(error_type, business_error_handler)
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(QuotaExceeded, quota_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(ResponseValidationError, unexpected_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
