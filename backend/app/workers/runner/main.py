from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from app.schemas.engine_catalog import EngineCatalogResponse
from app.services.provider_types import ProviderAccessContextRef, ProviderAccessMode
from app.workers.runner.contracts import (
    CancelCommand,
    CancelResponse,
    DownloadRequest,
    DownloadResponse,
    InspectRequest,
    InspectResponse,
    ProviderAccessContextContract,
    ProviderContextRequest,
    ProviderContextsRequest,
    ProviderContextsResponse,
    ProviderFailureContract,
    ProviderLoginRequest,
    RunnerErrorContract,
    RuntimeResponse,
    TaskStatusResponse,
)
from app.workers.runner.engine_catalog import RunnerEngineCatalog
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import configure_provider_instances
from app.workers.runner.provider_sessions import ProviderSessionStore
from app.workers.runner.readiness import RunnerReadiness, _runtime_packages_ready
from app.workers.runner.service import MediaRunnerService
from app.workers.runner.settings import RunnerSettings, get_runner_settings
from app.workers.runner.signing import (
    ExpiredSignatureError,
    HmacRequestAuthenticator,
    InMemoryNonceGuard,
    InvalidSignatureError,
    ReplayDetectedError,
    RequestAuthenticationError,
)
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

_TASK_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


async def _until_disconnect[ResultT](
    request: Request, operation: Awaitable[ResultT]
) -> ResultT:
    async def disconnected() -> None:
        # Authentication has consumed the request body. Waiting on ASGI receive
        # avoids polling CancelScope cancellation swallowing our own shutdown.
        while (await request.receive())["type"] != "http.disconnect":
            pass

    work = asyncio.ensure_future(operation)
    watcher = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait(
            {work, watcher}, return_when=asyncio.FIRST_COMPLETED
        )
        if work in done:
            return work.result()
        watcher.result()
        raise HTTPException(status_code=499, detail="operation_cancelled")
    finally:
        work.cancel()
        watcher.cancel()
        # The runner propagates cancellation into process-group termination and
        # private workspace cleanup before this request is released.
        await asyncio.gather(work, watcher, return_exceptions=True)


class RunnerService(Protocol):
    async def context(
        self, url: str, *, access_mode: ProviderAccessMode | None = None
    ) -> ProviderAccessContextRef: ...

    async def contexts_for_providers(
        self,
        provider_keys: tuple[str, ...],
        *,
        access_mode: ProviderAccessMode | None = None,
    ) -> tuple[ProviderAccessContextRef, ...]: ...

    async def inspect(
        self,
        url: str,
        *,
        access_context: ProviderAccessContextRef | None = None,
        deadline_at: datetime | None = None,
        allow_session_fallback: bool = True,
    ) -> InspectResponse: ...

    async def download(self, request: DownloadRequest) -> DownloadResponse: ...

    async def cancel(self, task_id: str) -> CancelResponse: ...

    async def status(self, task_id: str) -> TaskStatusResponse: ...


class ReadinessProbe(Protocol):
    async def check(self) -> bool: ...


def create_app(
    settings: RunnerSettings | None = None,
    *,
    service: RunnerService | None = None,
    readiness: ReadinessProbe | None = None,
) -> FastAPI:
    configured = settings or get_runner_settings()
    instance_id = uuid4().hex
    configure_provider_instances(configured.peertube_allowed_instances)
    sessions = ProviderSessionStore(configured)
    runner = service or MediaRunnerService(configured, session_store=sessions)
    readiness_probe = readiness or RunnerReadiness(configured)
    runtime_probe = RunnerReadiness(configured)
    engine_catalog = RunnerEngineCatalog(configured)
    authenticator = HmacRequestAuthenticator(
        configured.hmac_secret_bytes,
        nonce_guard=InMemoryNonceGuard(
            configured.runner_nonce_ttl_seconds,
            configured.runner_nonce_max_entries,
        ),
        max_age_seconds=configured.runner_signature_max_age_seconds,
        max_future_skew_seconds=configured.runner_signature_future_skew_seconds,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await sessions.close()

    app = FastAPI(
        title="Media Runner",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.exception_handler(RunnerFailure)
    async def runner_failure(_: Request, exc: RunnerFailure) -> JSONResponse:
        retry_after = exc.failure.retry_after
        headers = (
            {}
            if retry_after is None
            else {
                "Retry-After": str(
                    max(0, int((retry_after - datetime.now(UTC)).total_seconds()))
                )
            }
        )
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": RunnerErrorContract(
                    code=exc.code,
                    message=exc.message,
                    failure=ProviderFailureContract.from_domain(exc.failure),
                ).model_dump(mode="json")
            },
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def unexpected_failure(request: Request, __: Exception) -> JSONResponse:
        return await runner_failure(
            request, RunnerFailure("internal_error", status=500)
        )

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"service": "media-runner", "status": "live"}

    @app.get("/health/ready")
    async def ready() -> JSONResponse:
        if not await readiness_probe.check():
            return JSONResponse(
                status_code=503,
                content={"service": "media-runner", "status": "unavailable"},
            )
        return JSONResponse(content={"service": "media-runner", "status": "ready"})

    @app.get("/health/runtime")
    async def runtime_ready() -> JSONResponse:
        # Deployment health is independent of an optional platform session.
        # /health/ready continues to report actual platform readiness honestly.
        healthy = await runtime_probe.check()
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={
                "service": "media-runner",
                "status": "ready" if healthy else "unavailable",
            },
        )

    @app.get("/internal/runtime", response_model=RuntimeResponse)
    async def runtime(request: Request) -> RuntimeResponse:
        await _authenticated_body(request, configured, authenticator)
        return RuntimeResponse(instance_id=instance_id)

    def require_instance(request: Request) -> None:
        if request.headers.get("X-Runner-Instance") != instance_id:
            raise RunnerFailure("runner_restarted", status=409)

    @app.get("/internal/engine-catalog", response_model=EngineCatalogResponse)
    async def get_engine_catalog(request: Request) -> EngineCatalogResponse:
        await _authenticated_body(request, configured, authenticator)
        if configured.runner_access_mode is not ProviderAccessMode.ANONYMOUS:
            raise RunnerFailure("engine_catalog_unavailable", status=503)
        return await engine_catalog.get()

    @app.post("/internal/site-sessions/login")
    async def login(request: Request) -> dict[str, bool]:
        body = await _authenticated_body(request, configured, authenticator)
        payload = _parse(ProviderLoginRequest, body)
        await sessions.login(payload.url, finish=payload.finish)
        return {"opened": not payload.finish}

    @app.post("/internal/inspect", response_model=InspectResponse)
    async def inspect(request: Request) -> InspectResponse:
        body = await _authenticated_body(
            request,
            configured,
            authenticator,
        )
        require_instance(request)
        payload = _parse(InspectRequest, body)
        _require_pinned_engine(configured)
        return await _until_disconnect(
            request,
            runner.inspect(
                payload.url,
                access_context=(
                    None
                    if payload.access_context is None
                    else payload.access_context.to_domain()
                ),
                deadline_at=payload.deadline_at,
                **(
                    {"allow_session_fallback": False}
                    if not payload.allow_session_fallback
                    else {}
                ),
            ),
        )

    @app.post(
        "/internal/context",
        response_model=ProviderAccessContextContract,
    )
    async def context(request: Request) -> ProviderAccessContextContract:
        body = await _authenticated_body(
            request,
            configured,
            authenticator,
        )
        payload = _parse(ProviderContextRequest, body)
        _require_pinned_engine(configured)
        return ProviderAccessContextContract.from_domain(
            await runner.context(
                payload.url,
                **(
                    {"access_mode": payload.access_mode}
                    if payload.access_mode is not None
                    else {}
                ),
            )
        )

    @app.post(
        "/internal/contexts",
        response_model=ProviderContextsResponse,
    )
    async def contexts(request: Request) -> ProviderContextsResponse:
        body = await _authenticated_body(
            request,
            configured,
            authenticator,
        )
        payload = _parse(ProviderContextsRequest, body)
        _require_pinned_engine(configured)
        resolved = await runner.contexts_for_providers(
            tuple(payload.provider_keys),
            **(
                {"access_mode": payload.access_mode}
                if payload.access_mode is not None
                else {}
            ),
        )
        return ProviderContextsResponse(
            contexts=[
                ProviderAccessContextContract.from_domain(context)
                for context in resolved
            ]
        )

    @app.post("/internal/download", response_model=DownloadResponse)
    async def download(request: Request) -> DownloadResponse:
        body = await _authenticated_body(
            request,
            configured,
            authenticator,
        )
        require_instance(request)
        payload = _parse(DownloadRequest, body)
        _require_pinned_engine(configured)
        return await _until_disconnect(request, runner.download(payload))

    @app.post(
        "/internal/tasks/{task_id}/cancel",
        response_model=CancelResponse,
    )
    async def cancel(task_id: str, request: Request) -> CancelResponse:
        body = await _authenticated_body(
            request,
            configured,
            authenticator,
        )
        _parse(CancelCommand, body)
        if _TASK_ID.fullmatch(task_id) is None:
            raise RunnerFailure("invalid_request")
        return await runner.cancel(task_id)

    @app.get(
        "/internal/tasks/{task_id}",
        response_model=TaskStatusResponse,
    )
    async def status(task_id: str, request: Request) -> TaskStatusResponse:
        body = await _authenticated_body(
            request,
            configured,
            authenticator,
        )
        if body or _TASK_ID.fullmatch(task_id) is None:
            raise RunnerFailure("invalid_request")
        return await runner.status(task_id)

    return app


def _require_pinned_engine(settings: RunnerSettings) -> None:
    if not _runtime_packages_ready(settings):
        raise RunnerFailure("engine_unavailable", status=503)


async def _authenticated_body(
    request: Request,
    settings: RunnerSettings,
    authenticator: HmacRequestAuthenticator,
) -> bytes:
    if request.url.query:
        raise RunnerFailure("invalid_request")
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > settings.runner_max_request_bytes:
                raise RunnerFailure("request_too_large", status=413)
        except ValueError as exc:
            raise RunnerFailure("invalid_request") from exc
    body = await request.body()
    if len(body) > settings.runner_max_request_bytes:
        raise RunnerFailure("request_too_large", status=413)

    timestamp = request.headers.get("X-Runner-Timestamp")
    nonce = request.headers.get("X-Runner-Nonce")
    signature = request.headers.get("X-Runner-Signature")
    if timestamp is None or nonce is None or signature is None:
        raise RunnerFailure("authentication_required", status=401)
    try:
        parsed_timestamp = int(timestamp)
        authenticator.verify(
            request.method,
            request.url.path,
            body,
            parsed_timestamp,
            nonce,
            signature,
            now=int(time.time()),
            runtime_instance_id=request.headers.get("X-Runner-Instance"),
        )
    except ReplayDetectedError as exc:
        raise RunnerFailure("request_replayed", status=401) from exc
    except ExpiredSignatureError as exc:
        raise RunnerFailure("signature_expired", status=401) from exc
    except (InvalidSignatureError, RequestAuthenticationError, ValueError) as exc:
        raise RunnerFailure("invalid_signature", status=401) from exc
    return body


def _parse[ModelT: BaseModel](model: type[ModelT], body: bytes) -> ModelT:
    try:
        return model.model_validate_json(body)
    except ValidationError as exc:
        raise RunnerFailure("invalid_request") from exc
