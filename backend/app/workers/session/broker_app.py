"""HTTP entry point of the session broker.

Run with ``python -m app.workers.session.broker_app``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress

import httpx
import uvicorn
from app.core.config import Settings
from app.core.db import create_engine, create_session_factory
from app.core.security.site_session_cipher import SiteSessionCipher
from app.repositories.providers.site_sessions import (
    SiteSessionSecrets,
    SiteSessionStates,
)
from app.workers.session.broker import SessionBroker, SessionNotReady
from app.workers.session.browser_client import HttpSessionBrowser
from app.workers.session.contracts import (
    FAILURE_PATH,
    LEASE_PATH,
    STATUS_PATH,
    FailureReport,
    LeaseRequest,
    LeaseResponse,
    StatusRequest,
    StatusResponse,
)
from app.workers.session.rpc import SignedClient, authenticator, verified_model
from app.workers.session.sealing import SealError, decode_public_key, encode
from fastapi import FastAPI, HTTPException, Request, Response

BROKER_PORT = 19200
# Bootstrap waits for a real page load in the browser (60 s budget there).
_BROWSER_TIMEOUT_SECONDS = 90
_logger = logging.getLogger(__name__)

type BrokerFactory = Callable[[], AbstractAsyncContextManager[SessionBroker]]


def create_app(
    *, broker_factory: BrokerFactory, rpc_secret: bytes, scan_seconds: float
) -> FastAPI:
    verifier = authenticator(rpc_secret)
    health = {"scanned_at": 0.0}

    async def scan_forever(broker: SessionBroker) -> None:
        while True:
            try:
                await broker.scan()
                health["scanned_at"] = time.monotonic()
            except Exception:
                _logger.exception("site session scan failed")
            await asyncio.sleep(scan_seconds)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with broker_factory() as broker:
            app.state.broker = broker
            loop = asyncio.create_task(scan_forever(broker))
            try:
                yield
            finally:
                loop.cancel()
                with suppress(asyncio.CancelledError):
                    await loop

    app = FastAPI(
        title="Site Session Broker",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.post(STATUS_PATH, response_model=StatusResponse)
    async def status(request: Request) -> StatusResponse:
        body = await verified_model(request, verifier, StatusRequest)
        broker: SessionBroker = request.app.state.broker
        try:
            revision = await broker.ready_revision(body.site)
        except SessionNotReady:
            raise HTTPException(409, "provider_session_not_ready") from None
        return StatusResponse(site=body.site, seed_revision=revision)

    @app.post(LEASE_PATH, response_model=LeaseResponse)
    async def lease(request: Request) -> LeaseResponse:
        body = await verified_model(request, verifier, LeaseRequest)
        broker: SessionBroker = request.app.state.broker
        try:
            grant = await broker.lease(
                task_id=body.task_id,
                site=body.site,
                seed_revision=body.seed_revision,
                runner_key=decode_public_key(body.public_key),
            )
        except SessionNotReady:
            raise HTTPException(409, "provider_session_not_ready") from None
        except (SealError, ValueError):
            raise HTTPException(422, "invalid_request") from None
        return LeaseResponse(
            site=grant.site,
            seed_revision=grant.seed_revision,
            jar_version=grant.jar_version,
            expires_at=grant.expires_at,
            jar=encode(grant.jar),
            headers=None if grant.headers is None else encode(grant.headers),
        )

    @app.post(FAILURE_PATH, status_code=204)
    async def failure(request: Request) -> Response:
        body = await verified_model(request, verifier, FailureReport)
        broker: SessionBroker = request.app.state.broker
        await broker.report_failure(
            site=body.site, seed_revision=body.seed_revision, error_code=body.error_code
        )
        return Response(status_code=204)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready() -> Response:
        fresh = time.monotonic() - health["scanned_at"] <= scan_seconds * 3
        return Response(status_code=200 if health["scanned_at"] and fresh else 503)

    return app


def settings_factory(settings: Settings) -> BrokerFactory:
    key = settings.site_session_encryption_key
    browser_secret = settings.site_session_browser_secret
    if key is None or browser_secret is None:
        raise SystemExit(
            "session broker requires SITE_SESSION_ENCRYPTION_KEY and "
            "SITE_SESSION_BROWSER_SECRET"
        )

    @asynccontextmanager
    async def factory() -> AsyncIterator[SessionBroker]:
        engine = create_engine(settings.database_url)
        sessions = create_session_factory(engine)
        async with httpx.AsyncClient(
            base_url=settings.site_session_browser_url,
            timeout=_BROWSER_TIMEOUT_SECONDS,
        ) as client:
            try:
                yield SessionBroker(
                    states=SiteSessionStates(sessions),
                    secrets=SiteSessionSecrets(sessions),
                    cipher=SiteSessionCipher(key.get_secret_value()),
                    browser=HttpSessionBrowser(
                        SignedClient(client, browser_secret.get_secret_value().encode())
                    ),
                    lease_seconds=settings.site_session_lease_seconds,
                    keepalive_seconds=settings.site_session_keepalive_seconds,
                    keepalive_jitter_seconds=settings.site_session_keepalive_jitter_seconds,
                )
            finally:
                await engine.dispose()

    return factory


def main() -> None:
    settings = Settings(service_role="session-broker")
    rpc_secret = settings.site_session_rpc_secret
    if rpc_secret is None:
        raise SystemExit("session broker requires SITE_SESSION_RPC_SECRET")
    app = create_app(
        broker_factory=settings_factory(settings),
        rpc_secret=rpc_secret.get_secret_value().encode(),
        scan_seconds=settings.site_session_scan_seconds,
    )
    uvicorn.run(app, host="0.0.0.0", port=BROKER_PORT, access_log=False)


if __name__ == "__main__":
    main()
