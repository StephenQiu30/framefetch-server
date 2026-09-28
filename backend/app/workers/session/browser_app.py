"""HTTP entry point of the session browser.

Run with ``python -m app.workers.session.browser_app``. It holds no database
access and no encryption key: jars arrive sealed to a per-process X25519 key and
leave sealed to the key the broker (or a Runner) supplies with each call.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Protocol

import uvicorn
from app.services.site_sessions import InvalidSessionSite
from app.workers.session.browser import (
    OPERATION_TIMEOUT_SECONDS,
    HeadersUnavailable,
    SiteBrowser,
    VisitResult,
)
from app.workers.session.contracts import (
    BROWSER_BOOTSTRAP_PATH,
    BROWSER_FORGET_PATH,
    BROWSER_HEADERS_PATH,
    BROWSER_IDENTITY_PATH,
    BROWSER_KEEPALIVE_PATH,
    BootstrapRequest,
    BrowserIdentity,
    BrowserOutcome,
    BrowserResult,
    ForgetRequest,
    HeadersRequest,
    HeadersResponse,
    IdentityRequest,
    KeepaliveRequest,
    bootstrap_associated_data,
    export_associated_data,
    lease_associated_data,
)
from app.workers.session.rpc import authenticator, verified_model
from app.workers.session.sealing import (
    SealError,
    decode,
    decode_public_key,
    encode,
    open_sealed,
    public_key,
    seal,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fastapi import FastAPI, HTTPException, Request, Response
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BROWSER_PORT = 19300
# Two sites at a time bounds memory; the broker applies the same limit.
_CONCURRENCY = 2


class BrowserSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    site_session_browser_secret: SecretStr
    site_session_egress_proxy: str | None = None
    runner_provider_egress_proxies: dict[str, str] = Field(default_factory=dict)
    site_session_profile_root: Path = Path("/profiles")


class Browser(Protocol):
    async def bootstrap(self, site: str, jar: bytes) -> VisitResult: ...

    async def keepalive(self, site: str) -> VisitResult: ...

    async def headers(self, site: str) -> bytes: ...

    async def forget(self, site: str) -> None: ...


type BrowserFactory = Callable[[], AbstractAsyncContextManager[Browser]]


def create_app(*, browser_factory: BrowserFactory, secret: bytes) -> FastAPI:
    verifier = authenticator(secret)
    identity = X25519PrivateKey.generate()
    slots = asyncio.Semaphore(_CONCURRENCY)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with browser_factory() as browser:
            app.state.browser = browser
            yield

    app = FastAPI(
        title="Site Session Browser",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    def browser_of(request: Request) -> Browser:
        return request.app.state.browser  # type: ignore[no-any-return]

    async def bounded(operation: object) -> VisitResult:
        async with slots:
            try:
                async with asyncio.timeout(OPERATION_TIMEOUT_SECONDS):
                    return await operation  # type: ignore[misc,no-any-return]
            except (TimeoutError, PlaywrightError, OSError):
                return VisitResult(BrowserOutcome.UNAVAILABLE)

    @app.post(BROWSER_IDENTITY_PATH, response_model=BrowserIdentity)
    async def get_identity(request: Request) -> BrowserIdentity:
        await verified_model(request, verifier, IdentityRequest)
        return BrowserIdentity(public_key=encode(public_key(identity)))

    @app.post(BROWSER_BOOTSTRAP_PATH, response_model=BrowserResult)
    async def bootstrap(request: Request) -> BrowserResult:
        body = await verified_model(request, verifier, BootstrapRequest)
        try:
            jar = open_sealed(
                decode(body.jar),
                identity,
                associated_data=bootstrap_associated_data(
                    body.site, body.seed_revision
                ),
            )
            reply = decode_public_key(body.reply_key)
            result = await bounded(browser_of(request).bootstrap(body.site, jar))
        except (SealError, ValueError, InvalidSessionSite):
            raise HTTPException(422, "invalid_request") from None
        return _result(result, reply, body.site, body.seed_revision)

    @app.post(BROWSER_KEEPALIVE_PATH, response_model=BrowserResult)
    async def keepalive(request: Request) -> BrowserResult:
        body = await verified_model(request, verifier, KeepaliveRequest)
        try:
            reply = decode_public_key(body.reply_key)
            result = await bounded(browser_of(request).keepalive(body.site))
        except (SealError, ValueError, InvalidSessionSite):
            raise HTTPException(422, "invalid_request") from None
        return _result(result, reply, body.site, body.seed_revision)

    @app.post(BROWSER_HEADERS_PATH, response_model=HeadersResponse)
    async def headers(request: Request) -> HeadersResponse:
        body = await verified_model(request, verifier, HeadersRequest)
        try:
            runner = decode_public_key(body.public_key)
            async with slots, asyncio.timeout(OPERATION_TIMEOUT_SECONDS):
                payload = await browser_of(request).headers(body.site)
        except (SealError, ValueError, InvalidSessionSite):
            raise HTTPException(422, "invalid_request") from None
        except (HeadersUnavailable, TimeoutError, PlaywrightError, OSError):
            raise HTTPException(503, "provider_session_not_ready") from None
        sealed = seal(
            payload,
            runner,
            associated_data=lease_associated_data(
                "headers", body.task_id, body.site, body.seed_revision, body.expires_at
            ),
        )
        return HeadersResponse(headers=encode(sealed))

    @app.post(BROWSER_FORGET_PATH, status_code=204)
    async def forget(request: Request) -> Response:
        body = await verified_model(request, verifier, ForgetRequest)
        try:
            await browser_of(request).forget(body.site)
        except InvalidSessionSite:
            raise HTTPException(422, "invalid_request") from None
        return Response(status_code=204)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _result(
    result: VisitResult, reply: bytes, site: str, seed_revision: int
) -> BrowserResult:
    jar = None
    if result.jar is not None:
        jar = encode(
            seal(
                result.jar,
                reply,
                associated_data=export_associated_data(site, seed_revision),
            )
        )
    return BrowserResult(outcome=result.outcome, error_code=result.error_code, jar=jar)


def main() -> None:
    settings = BrowserSettings()

    @asynccontextmanager
    async def browser_factory() -> AsyncIterator[Browser]:
        async with async_playwright() as playwright:
            yield SiteBrowser(
                playwright,
                settings.site_session_profile_root,
                proxy=settings.site_session_egress_proxy,
                provider_proxies=settings.runner_provider_egress_proxies,
            )

    app = create_app(
        browser_factory=browser_factory,
        secret=settings.site_session_browser_secret.get_secret_value().encode(),
    )
    uvicorn.run(app, host="0.0.0.0", port=BROWSER_PORT, access_log=False)


if __name__ == "__main__":
    main()
