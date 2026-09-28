"""Request-scoped dependencies shared by API routes."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Header, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.requests import HTTPConnection

from app.api.operation_logging import identify_operation_actor
from app.core.config import Settings
from app.core.errors import AppError
from app.core.runtime import (
    AnalysisUseCases,
    ApiServices,
    DocumentImportUseCases,
    DownloadUseCases,
    MediaImportUseCases,
    SourceDiscoveryUseCases,
)
from app.services.ai_providers import AiProviderService
from app.services.auth.errors import AuthError
from app.services.auth.models import CurrentUser, UserRole
from app.services.auth.service import AuthService
from app.services.auth.user_service import UserService
from app.services.auth.web_sessions import WebSessionGrant, WebSessionService
from app.services.downloads.ports import DownloadArtifactStorage
from app.services.history_records import HistoryRecordService
from app.services.provider_catalog import ProviderCatalogService
from app.services.providers import ProviderStatusView
from app.services.storage_files.service import StorageFileService

IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        description="同一业务操作的安全重试必须复用相同键值。",
        examples=["01J4Z3Q9A7M2F6K8P0R1T5V7WX"],
        min_length=1,
        max_length=128,
    ),
]


def get_runtime_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_download_storage(request: Request) -> DownloadArtifactStorage:
    return require_service(get_services(request).download_storage, "download storage")


def get_download_use_cases(request: Request) -> DownloadUseCases:
    return require_service(get_services(request).download_use_cases, "download")


def get_source_discovery_use_cases(request: Request) -> SourceDiscoveryUseCases:
    return require_service(
        get_services(request).source_discovery_use_cases, "source discovery"
    )


def get_analysis_use_cases(request: Request) -> AnalysisUseCases:
    return require_service(get_services(request).analysis_use_cases, "analysis")


def get_history_record_service(request: Request) -> HistoryRecordService:
    return require_service(
        get_services(request).history_record_service, "history records"
    )


def get_media_import_use_cases(request: Request) -> MediaImportUseCases:
    return require_service(get_services(request).media_import_use_cases, "media import")


def get_document_import_use_cases(request: Request) -> DocumentImportUseCases:
    return require_service(
        get_services(request).document_import_use_cases, "document import"
    )


def get_provider_catalog_service(request: Request) -> ProviderCatalogService:
    return require_service(
        get_services(request).provider_catalog_service, "Provider catalog"
    )


def get_ai_provider_service(request: Request) -> AiProviderService:
    return require_service(get_services(request).ai_provider_service, "AI Provider")


def get_storage_file_service(request: Request) -> StorageFileService:
    return require_service(get_services(request).storage_file_service, "storage file")


async def get_provider_statuses(request: Request) -> tuple[ProviderStatusView, ...]:
    service = get_services(request).provider_status_service
    if service is not None:
        return await service.list()
    return cast(tuple[ProviderStatusView, ...], request.app.state.provider_statuses)


def get_services(connection: HTTPConnection) -> ApiServices:
    return cast(ApiServices, connection.app.state.services)


def require_service[T](service: T | None, name: str) -> T:
    if service is None:
        raise AppError(
            status=503,
            code="service_unavailable",
            title="Service unavailable",
            detail=f"The {name} service is not available.",
        )
    return service


native_bearer = HTTPBearer(auto_error=False, scheme_name="NativeBearerAuth")


def get_auth_service(request: Request) -> AuthService:
    return require_service(get_services(request).auth_service, "authentication")


def get_user_service(request: Request) -> UserService:
    return require_service(get_services(request).user_service, "user")


def get_web_session_service(request: Request) -> WebSessionService:
    return require_service(get_services(request).web_session_service, "Web session")


async def get_native_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(native_bearer)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> CurrentUser:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise _unauthenticated()
    try:
        user = await auth.current_user(credentials.credentials)
        identify_operation_actor(user)
        return user
    except AuthError as exc:
        raise _unauthenticated() from exc


async def get_web_user(
    request: Request,
    settings: Annotated[Settings, Depends(get_runtime_settings)],
    web: Annotated[WebSessionService, Depends(get_web_session_service)],
) -> CurrentUser:
    if request.headers.get("authorization") is not None:
        raise _unauthenticated()
    try:
        user = await web.current_user(
            request.cookies.get(settings.auth_web_cookie_name, "")
        )
        identify_operation_actor(user)
        return user
    except AuthError as exc:
        raise _unauthenticated() from exc


async def get_current_user(
    request: Request,
    settings: Annotated[Settings, Depends(get_runtime_settings)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(native_bearer)],
) -> CurrentUser:
    # Explicit credentials choose exactly one transport; invalid Bearer never
    # falls back to ambient browser identity.
    if request.headers.get("authorization") is not None:
        return await get_native_user(credentials, get_auth_service(request))
    return await get_web_user(request, settings, get_web_session_service(request))


async def get_current_admin(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUser:
    if user.role is not UserRole.ADMIN:
        raise AppError(
            status=403,
            code="forbidden",
            title="Forbidden",
            detail="Administrator access is required.",
        )
    return user


def set_auth_cookies(
    response: Response, settings: Settings, grant: WebSessionGrant
) -> None:
    response.set_cookie(
        key=settings.auth_web_cookie_name,
        value=grant.token,
        max_age=settings.auth_web_absolute_ttl_seconds,
        expires=grant.expires_at,
        httponly=True,
        secure=settings.app_env in {"staging", "production"},
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.auth_web_cookie_name,
        httponly=True,
        secure=settings.app_env in {"staging", "production"},
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


def _unauthenticated() -> AppError:
    return AppError(
        status=401,
        code="unauthenticated",
        title="Authentication required",
        detail="Sign in to continue.",
    )
