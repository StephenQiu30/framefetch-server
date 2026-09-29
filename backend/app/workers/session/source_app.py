"""Host browser source: signed control and end-to-end sealed, per-task leases."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.workers.session.chrome_source import (
    CONNECT_PATH,
    DISCONNECT_PATH,
    POLL_PATH,
    REPLY_PATH,
    BrowserConnection,
    BrowserReply,
    ChromeSource,
    SourceUnavailable,
)
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
    lease_associated_data,
)
from app.workers.session.rpc import authenticator, verified_model
from app.workers.session.sealing import SealError, decode_public_key, encode, seal
from fastapi import FastAPI, HTTPException, Request, Response


def create_app(
    *, source: ChromeSource, secret: bytes, lease_seconds: int = 600
) -> FastAPI:
    verifier = authenticator(secret)
    ready = False

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal ready
        await source.start()
        ready = True
        try:
            yield
        finally:
            ready = False
            await source.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.exception_handler(SourceUnavailable)
    async def unavailable(request: Request, error: SourceUnavailable) -> Response:
        from fastapi.responses import JSONResponse

        status = (
            409 if error.code in {"credential_required", "credential_revoked"} else 503
        )
        return JSONResponse({"detail": error.code}, status_code=status)

    @app.post(CONNECT_PATH)
    async def connect(request: Request) -> BrowserConnection:
        from pydantic import BaseModel, ConfigDict

        class ConnectRequest(BaseModel):
            model_config = ConfigDict(extra="forbid")

        await verified_model(request, verifier, ConnectRequest)
        return source.connect()

    @app.post(DISCONNECT_PATH)
    async def disconnect(request: Request) -> dict[str, bool]:
        body = await verified_model(request, verifier, BrowserConnection)
        source.disconnect(body.connection)
        return {"accepted": True}

    @app.post(POLL_PATH)
    async def poll(request: Request) -> dict[str, object]:
        body = await verified_model(request, verifier, BrowserConnection)
        return await source.poll(body.connection)

    @app.post(REPLY_PATH)
    async def browser_reply(request: Request) -> dict[str, bool]:
        body = await verified_model(request, verifier, BrowserReply)
        source.reply(body)
        return {"accepted": True}

    @app.post(STATUS_PATH, response_model=StatusResponse)
    async def status(request: Request) -> StatusResponse:
        body = await verified_model(request, verifier, StatusRequest)
        snapshot = await source.read(body.site)
        return StatusResponse(site=body.site, source_generation=snapshot.generation)

    @app.post(LOGIN_PATH, response_model=LoginResponse)
    async def login(request: Request) -> LoginResponse:
        body = await verified_model(request, verifier, LoginRequest)
        if body.finish:
            await source.finish_login(body.site)
        else:
            await source.open_login(body.site)
        return LoginResponse(site=body.site, opened=not body.finish)

    @app.post(LEASE_PATH, response_model=LeaseResponse)
    async def lease(request: Request) -> LeaseResponse:
        body = await verified_model(request, verifier, LeaseRequest)
        try:
            recipient = decode_public_key(body.public_key)
        except SealError:
            raise HTTPException(422, "invalid_request") from None
        snapshot = await source.read(body.site, include_headers=True)
        if snapshot.generation != body.source_generation:
            raise SourceUnavailable("credential_revoked")
        expires = int(time.time()) + lease_seconds

        def sealed(kind: str, payload: bytes) -> str:
            return encode(
                seal(
                    payload,
                    recipient,
                    associated_data=lease_associated_data(
                        kind, body.task_id, body.site, snapshot.generation, expires
                    ),
                )
            )

        return LeaseResponse(
            site=body.site,
            source_generation=snapshot.generation,
            expires_at=expires,
            jar=sealed("jar", snapshot.cookies),
            headers=None
            if snapshot.headers is None
            else sealed("headers", snapshot.headers),
        )

    @app.get("/health")
    async def health() -> Response:
        return Response(status_code=200 if ready else 503)

    return app
