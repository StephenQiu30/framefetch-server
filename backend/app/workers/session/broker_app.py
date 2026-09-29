"""Narrow bridge across the container network boundary; never decrypts sessions.

The media sandbox cannot reach the host directly. This relay has only two RPC
keys and forwards sealed leases; platform state lives in the browser source.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import uvicorn
from app.core.config import Settings
from app.workers.session.contracts import (
    LEASE_PATH,
    LOGIN_PATH,
    STATUS_PATH,
    LeaseRequest,
    LeaseResponse,
    LoginRequest,
    LoginResponse,
    StatusRequest,
    StatusResponse,
)
from app.workers.session.rpc import (
    RpcError,
    SignedClient,
    authenticator,
    verified_model,
)
from fastapi import FastAPI, HTTPException, Request, Response

type SourceFactory = Callable[[], AbstractAsyncContextManager[SignedClient]]


def create_app(*, source_factory: SourceFactory, rpc_secret: bytes) -> FastAPI:
    verifier = authenticator(rpc_secret)
    source: SignedClient | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal source
        async with source_factory() as client:
            source = client
            try:
                yield
            finally:
                source = None

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.exception_handler(RpcError)
    async def rpc_error(request: Request, error: RpcError) -> Response:
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": error.code}, status_code=error.status)

    def connected() -> SignedClient:
        if source is None:
            raise HTTPException(503, "provider_session_not_ready")
        return source

    @app.post(STATUS_PATH, response_model=StatusResponse)
    async def status(request: Request) -> StatusResponse:
        body = await verified_model(request, verifier, StatusRequest)
        return await connected().post(STATUS_PATH, body, StatusResponse)

    @app.post(LEASE_PATH, response_model=LeaseResponse)
    async def lease(request: Request) -> LeaseResponse:
        body = await verified_model(request, verifier, LeaseRequest)
        return await connected().post(LEASE_PATH, body, LeaseResponse)

    @app.post(LOGIN_PATH, response_model=LoginResponse)
    async def login(request: Request) -> LoginResponse:
        body = await verified_model(request, verifier, LoginRequest)
        return await connected().post(LOGIN_PATH, body, LoginResponse)

    @app.get("/health/live")
    async def live() -> Response:
        return Response(status_code=200)

    @app.get("/health/ready")
    async def ready() -> Response:
        return Response(status_code=200 if source is not None else 503)

    return app


def settings_factory(settings: Settings) -> SourceFactory:
    secret = settings.site_session_agent_secret
    if secret is None:
        raise SystemExit("session bridge requires SITE_SESSION_AGENT_SECRET")

    @asynccontextmanager
    async def factory() -> AsyncIterator[SignedClient]:
        async with httpx.AsyncClient(
            base_url=settings.site_session_agent_url, timeout=65, trust_env=False
        ) as client:
            yield SignedClient(client, secret.get_secret_value().encode())

    return factory


def main() -> None:
    settings = Settings(service_role="session-broker")
    secret = settings.site_session_rpc_secret
    if secret is None:
        raise SystemExit("session bridge requires SITE_SESSION_RPC_SECRET")
    uvicorn.run(
        create_app(
            source_factory=settings_factory(settings),
            rpc_secret=secret.get_secret_value().encode(),
        ),
        host="0.0.0.0",
        port=19200,
        access_log=False,
    )


if __name__ == "__main__":
    main()
