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
from app.workers.session.chrome_broker import (
    ChromeSessionBroker,
    SessionLoginRequired,
    SessionNotReady,
)
from app.workers.session.contracts import (
    FAILURE_PATH,
    LEASE_PATH,
    ROTATION_PATH,
    STATUS_PATH,
    FailureReport,
    LeaseRequest,
    LeaseResponse,
    RotationReport,
    StatusRequest,
    StatusResponse,
)
from app.workers.session.rpc import SignedClient, authenticator, verified_model
from app.workers.session.sealing import SealError, decode, decode_public_key, encode
from fastapi import FastAPI, HTTPException, Request, Response

BROKER_PORT = 19200
# Reading Chrome's Cookie store and keychain takes well under a second.
_AGENT_TIMEOUT_SECONDS = 30
_logger = logging.getLogger(__name__)

type BrokerFactory = Callable[[], AbstractAsyncContextManager[ChromeSessionBroker]]


def create_app(
    *,
    broker_factory: BrokerFactory,
    rpc_secret: bytes,
    scan_seconds: float,
    warmup_seconds: float = 60,
) -> FastAPI:
    verifier = authenticator(rpc_secret)
    health = {"scanned_at": 0.0, "warm": False}
    started = time.monotonic()

    async def scan_forever(broker: ChromeSessionBroker) -> None:
        while True:
            try:
                health["scanned_at"] = time.monotonic()
                await asyncio.wait_for(broker.scan(), timeout=180)
                health["scanned_at"] = time.monotonic()
            except Exception:
                health["scanned_at"] = 0.0
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
        broker: ChromeSessionBroker = request.app.state.broker
        try:
            revision = await broker.ready_revision(body.site)
        except SessionLoginRequired:
            raise HTTPException(409, "credential_required") from None
        except SessionNotReady:
            raise HTTPException(409, "provider_session_not_ready") from None
        return StatusResponse(site=body.site, seed_revision=revision)

    @app.post(LEASE_PATH, response_model=LeaseResponse)
    async def lease(request: Request) -> LeaseResponse:
        body = await verified_model(request, verifier, LeaseRequest)
        broker: ChromeSessionBroker = request.app.state.broker
        try:
            grant = await broker.lease(
                task_id=body.task_id,
                site=body.site,
                seed_revision=body.seed_revision,
                runner_key=decode_public_key(body.public_key),
            )
        except SessionLoginRequired:
            raise HTTPException(409, "credential_required") from None
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
            rotation_key=encode(grant.rotation_key),
            headers=None if grant.headers is None else encode(grant.headers),
        )

    @app.post(ROTATION_PATH, status_code=204)
    async def rotation(request: Request) -> Response:
        body = await verified_model(request, verifier, RotationReport)
        broker: ChromeSessionBroker = request.app.state.broker
        try:
            await broker.absorb_rotation(
                task_id=body.task_id,
                site=body.site,
                seed_revision=body.seed_revision,
                sealed_jar=decode(body.jar),
            )
        except (SessionNotReady, SealError):
            raise HTTPException(409, "provider_session_not_ready") from None
        return Response(status_code=204)

    @app.post(FAILURE_PATH, status_code=204)
    async def failure(request: Request) -> Response:
        body = await verified_model(request, verifier, FailureReport)
        broker: ChromeSessionBroker = request.app.state.broker
        await broker.report_failure(
            site=body.site, seed_revision=body.seed_revision, error_code=body.error_code
        )
        return Response(status_code=204)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready(request: Request) -> Response:
        fresh = time.monotonic() - health["scanned_at"] <= 180 + scan_seconds * 3
        if not (health["scanned_at"] and fresh):
            return Response(status_code=503)
        # After a cold start, report ready only once sessions stored as ready are
        # verified live, so ``compose up --wait`` means "platforms are usable".
        # Bounded and latched: a session that never verifies must not keep the
        # broker (and everything waiting on it) unhealthy forever.
        if not health["warm"]:
            broker: ChromeSessionBroker = request.app.state.broker
            try:
                warming = await broker.warming_up()
            except Exception:
                warming = False
            if warming and time.monotonic() - started < warmup_seconds:
                return Response(status_code=503)
            health["warm"] = True
        return Response(status_code=200)

    return app


def settings_factory(settings: Settings) -> BrokerFactory:
    secret = settings.site_session_agent_secret
    if secret is None:
        raise SystemExit("session broker requires SITE_SESSION_AGENT_SECRET")

    @asynccontextmanager
    async def factory() -> AsyncIterator[ChromeSessionBroker]:
        async with httpx.AsyncClient(
            base_url=settings.site_session_agent_url,
            timeout=_AGENT_TIMEOUT_SECONDS,
        ) as client:
            yield ChromeSessionBroker(
                SignedClient(client, secret.get_secret_value().encode()),
                lease_seconds=settings.site_session_lease_seconds,
            )

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
