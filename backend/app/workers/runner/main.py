from __future__ import annotations

import asyncio
import math
import re
import secrets
import time
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from app.schemas.engine_catalog import EngineCatalogResponse
from app.services.provider_types import ExecutionContext
from app.workers.runner.contracts import (
    CancelCommand,
    CancelResponse,
    DownloadRequest,
    DownloadResponse,
    InspectRequest,
    InspectResponse,
    ProviderFailureContract,
    RunnerErrorContract,
    RuntimeResponse,
    TaskStatusResponse,
)
from app.workers.runner.engine.identity import initialize_identity_tmpfs
from app.workers.runner.engine_catalog import RunnerEngineCatalog
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import configure_provider_instances
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
_PROTOCOL_ERRORS = frozenset(
    {
        "authentication_required",
        "invalid_signature",
        "signature_expired",
        "request_replayed",
        "invalid_request",
        "request_too_large",
        "runner_restarted",
        "task_not_found",
    }
)


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
    async def inspect(
        self,
        url: str,
        *,
        execution_context: ExecutionContext | None = None,
        task_id: str | None = None,
        deadline: datetime | None = None,
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
    runner = service or MediaRunnerService(configured)
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
            initialize_identity_tmpfs(configured.runner_identity_tmpfs_root)
            if configured.runner_browser_enabled:
                from app.workers.runner.browser_runtime import initialize_browser_tmpfs

                initialize_browser_tmpfs(configured.runner_browser_temp_root)
            yield
        finally:
            if service is None:
                assert isinstance(runner, MediaRunnerService)
                await runner.close()

    app = FastAPI(
        title="Media Runner",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.exception_handler(RunnerFailure)
    async def runner_failure(_: Request, exc: RunnerFailure) -> JSONResponse:
        failure = exc.failure
        if exc.code not in _PROTOCOL_ERRORS:
            failure = replace(failure, code=failure.failure_class.value)
        retry_after = failure.retry_after
        headers = (
            {}
            if retry_after is None
            else {
                "Retry-After": str(
                    max(0, math.ceil((retry_after - datetime.now(UTC)).total_seconds()))
                )
            }
        )
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": RunnerErrorContract(
                    code=failure.code,
                    message=failure.summary,
                    failure=ProviderFailureContract.from_domain(failure),
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
        return await engine_catalog.get()

    # This short-lived admission barrier only spans the signed request lifetime.
    # An ACK nonce proves the successor was issued after confirmed cleanup; wall
    # clock skew cannot let an older signed request cross this barrier. Recovery
    # reuses the resource ID with that nonce, without a business operation ledger.
    cancelled_before: dict[str, datetime] = {}
    cancelling: dict[str, int] = {}
    cleanup_tokens: dict[str, str] = {}

    def prune_cancel_barriers(now: datetime) -> None:
        lifetime = timedelta(
            seconds=configured.runner_signature_max_age_seconds
            + configured.runner_signature_future_skew_seconds
            + 1
        )
        for task_id, cutoff in tuple(cancelled_before.items()):
            if task_id not in cancelling and now - cutoff > lifetime:
                cancelled_before.pop(task_id)
                cancelling.pop(task_id, None)
                cleanup_tokens.pop(task_id, None)

    def require_admission(
        task_id: str,
        issued_at: datetime,
        deadline: datetime | None,
        cleanup_token: str | None,
        request: Request,
    ) -> None:
        now = datetime.now(UTC)
        signed_at = int(request.headers["X-Runner-Timestamp"])
        age = now.timestamp() - signed_at
        if (
            age > configured.runner_signature_max_age_seconds
            or age < -configured.runner_signature_future_skew_seconds
        ):
            raise RunnerFailure("signature_expired", status=401)
        prune_cancel_barriers(now)
        if abs(issued_at.timestamp() - signed_at) > 1:
            raise RunnerFailure("invalid_request")
        if deadline is not None and deadline <= now:
            raise RunnerFailure("inspection_timeout", status=504)
        if task_id in cancelling:
            raise RunnerFailure("cancellation_pending", status=409)
        expected_token = cleanup_tokens.get(task_id)
        if expected_token is not None and cleanup_token != expected_token:
            raise RunnerFailure("cancelled", status=409)

    @app.post("/internal/inspect", response_model=InspectResponse)
    async def inspect(request: Request) -> InspectResponse:
        body = await _authenticated_body(
            request,
            configured,
            authenticator,
        )
        require_instance(request)
        payload = _parse(InspectRequest, body)
        if "issued_at" not in payload.model_fields_set:
            raise RunnerFailure("invalid_request")
        _require_engine_runtime(configured)

        async def admitted_inspect() -> InspectResponse:
            # Run inside the actual work task. No await separates this check from
            # MediaRunnerService registering its resources at the first entry.
            require_admission(
                payload.task_id,
                payload.issued_at,
                payload.deadline,
                payload.cleanup_token,
                request,
            )
            return await runner.inspect(
                payload.url,
                task_id=payload.task_id,
                deadline=payload.deadline,
                execution_context=None
                if payload.execution_context is None
                else payload.execution_context.to_domain(),
            )

        return await _until_disconnect(request, admitted_inspect())

    @app.post("/internal/download", response_model=DownloadResponse)
    async def download(request: Request) -> DownloadResponse:
        body = await _authenticated_body(
            request,
            configured,
            authenticator,
        )
        require_instance(request)
        payload = _parse(DownloadRequest, body)
        if "issued_at" not in payload.model_fields_set:
            raise RunnerFailure("invalid_request")
        _require_engine_runtime(configured)

        async def admitted_download() -> DownloadResponse:
            require_admission(
                payload.task_id,
                payload.issued_at,
                payload.deadline,
                payload.cleanup_token,
                request,
            )
            return await runner.download(payload)

        return await _until_disconnect(request, admitted_download())

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
        require_instance(request)
        _parse(CancelCommand, body)
        if _TASK_ID.fullmatch(task_id) is None:
            raise RunnerFailure("invalid_request")
        now = datetime.now(UTC)
        prune_cancel_barriers(now)
        if (
            task_id not in cancelled_before
            and len(cancelled_before) >= configured.runner_nonce_max_entries
        ):
            await runner.cancel(task_id)
            raise RunnerFailure("cancellation_pending", status=503)
        cancelling[task_id] = cancelling.get(task_id, 0) + 1
        cancelled_before[task_id] = datetime.now(UTC)
        cleanup_tokens[task_id] = secrets.token_hex(16)
        confirmed = False
        try:
            response = await runner.cancel(task_id)
            confirmed = True
        finally:
            remaining_cancellations = max(0, cancelling.get(task_id, 1) - 1)
            if confirmed and remaining_cancellations == 0:
                cancelling.pop(task_id, None)
            else:
                cancelling[task_id] = remaining_cancellations
        cancelled_before[task_id] = datetime.now(UTC)
        return response.model_copy(update={"cleanup_token": cleanup_tokens[task_id]})

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


def _require_engine_runtime(settings: RunnerSettings) -> None:
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
