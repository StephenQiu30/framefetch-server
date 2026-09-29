"""HTTP entry point of the session broker.

Run with ``python -m app.workers.session.broker_app``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import uvicorn
from app.core.config import Settings
from app.workers.session.chrome_broker import (
    ChromeSessionBroker,
    SessionLoginRequired,
    SessionNotReady,
)
from app.workers.session.contracts import (
    LEASE_PATH,
    STATUS_PATH,
    LeaseRequest,
    LeaseResponse,
    StatusRequest,
    StatusResponse,
)
from app.workers.session.rpc import SignedClient, authenticator, verified_model
from app.workers.session.sealing import SealError, decode_public_key, encode
from fastapi import FastAPI, HTTPException, Request, Response

BROKER_PORT = 19200
_AGENT_TIMEOUT_SECONDS = 30

type BrokerFactory = Callable[[], AbstractAsyncContextManager[ChromeSessionBroker]]


def create_app(
    *,
    broker_factory: BrokerFactory,
    rpc_secret: bytes,
) -> FastAPI:
    verifier = authenticator(rpc_secret)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with broker_factory() as broker:
            app.state.broker = broker
            try:
                yield
            finally:
                del app.state.broker

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
            expires_at=grant.expires_at,
            jar=encode(grant.jar),
            headers=None if grant.headers is None else encode(grant.headers),
        )

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready(request: Request) -> Response:
        # Readiness describes this relay's lifecycle, not a platform login.
        # STATUS_PATH and LEASE_PATH report source failures on demand.
        return Response(
            status_code=200 if hasattr(request.app.state, "broker") else 503
        )

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
    )
    uvicorn.run(app, host="0.0.0.0", port=BROKER_PORT, access_log=False)


if __name__ == "__main__":
    main()
