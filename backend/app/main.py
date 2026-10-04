"""FastAPI process entry point."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from app.api.errors import (
    register_exception_handlers,
)
from app.api.middleware import request_guard
from app.api.openapi import (
    API_DESCRIPTION,
    ERROR_RESPONSES,
    OPENAPI_TAGS,
    SWAGGER_UI_PARAMETERS,
)
from app.api.routes.admin_ai_providers import router as admin_ai_providers_router
from app.api.routes.admin_analyses import router as admin_analyses_router
from app.api.routes.admin_downloads import router as admin_downloads_router
from app.api.routes.admin_files import router as admin_files_router
from app.api.routes.admin_operation_logs import router as admin_operation_logs_router
from app.api.routes.admin_provider_runtime import (
    router as admin_provider_runtime_router,
)
from app.api.routes.admin_providers import router as admin_providers_router
from app.api.routes.admin_users import router as admin_users_router
from app.api.routes.analyses import router as analyses_router
from app.api.routes.auth import router as auth_router
from app.api.routes.content_analyses import router as content_analyses_router
from app.api.routes.creation import router as creation_router
from app.api.routes.creation_exports import router as creation_exports_router
from app.api.routes.document_analyses import router as document_analyses_router
from app.api.routes.documents import router as documents_router
from app.api.routes.download_intents import router as download_intents_router
from app.api.routes.downloads import router as downloads_router
from app.api.routes.health import router as health_router
from app.api.routes.inspections import router as inspections_router
from app.api.routes.media_imports import router as media_imports_router
from app.api.routes.metrics import router as metrics_router
from app.api.routes.native_auth import router as native_auth_router
from app.api.routes.native_openapi import router as native_openapi_router
from app.api.routes.providers import router as providers_router
from app.api.routes.source_discoveries import router as source_discoveries_router
from app.api.routes.task_socket import router as task_socket_router
from app.api.routes.users import router as users_router
from app.core.config import Settings, get_settings
from app.core.lifespan import api_lifespan
from app.core.runtime import ApiRuntime, ApiServices
from app.integrations.provider_status import configured_provider_statuses


def create_app(
    settings: Settings | None = None,
    runtime: ApiRuntime | None = None,
) -> FastAPI:
    effective = settings or get_settings()
    application = FastAPI(
        title="视频下载与分析服务 API",
        description=API_DESCRIPTION,
        docs_url="/docs",
        license_info={"name": "MIT", "identifier": "MIT"},
        openapi_tags=OPENAPI_TAGS,
        openapi_url="/openapi.json",
        redoc_url="/redoc",
        swagger_ui_parameters=SWAGGER_UI_PARAMETERS,
        version=effective.app_version,
        lifespan=lambda application: api_lifespan(application, effective, runtime),
    )
    application.state.settings = effective
    application.state.provider_statuses = configured_provider_statuses()
    application.state.services = runtime.services if runtime else ApiServices()
    application.include_router(health_router)
    application.include_router(metrics_router)
    application.include_router(native_auth_router)
    application.include_router(native_openapi_router)

    api_router = APIRouter(prefix="/api", responses=ERROR_RESPONSES)
    api_router.include_router(auth_router)
    api_router.include_router(users_router)
    api_router.include_router(admin_users_router)
    api_router.include_router(admin_operation_logs_router)
    api_router.include_router(admin_downloads_router)
    api_router.include_router(admin_analyses_router)
    api_router.include_router(admin_files_router)
    api_router.include_router(admin_ai_providers_router)
    api_router.include_router(admin_providers_router)
    api_router.include_router(admin_provider_runtime_router)
    api_router.include_router(inspections_router)
    api_router.include_router(download_intents_router)
    api_router.include_router(source_discoveries_router)
    api_router.include_router(providers_router)
    api_router.include_router(downloads_router)
    api_router.include_router(documents_router)
    api_router.include_router(document_analyses_router)
    api_router.include_router(media_imports_router)
    api_router.include_router(analyses_router)
    api_router.include_router(content_analyses_router)
    api_router.include_router(creation_exports_router)
    api_router.include_router(creation_router)
    api_router.include_router(task_socket_router)
    application.include_router(api_router)
    application.middleware("http")(
        lambda request, call_next: request_guard(
            request,
            call_next,
            max_body_bytes=effective.request_max_bytes,
            timeout_seconds=effective.request_timeout_seconds,
            production=effective.app_env == "production",
            connect_origins=(
                (effective.minio_public_origin(),)
                if effective.media_import_enabled or effective.document_import_enabled
                else ()
            ),
            media_origins=(
                (effective.minio_public_origin(),)
                if effective.media_import_enabled
                else ()
            ),
        )
    )
    register_exception_handlers(application)
    return application


app = create_app()


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    run()
