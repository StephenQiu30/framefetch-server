"""HTTP entry point of the session browser.

Run with ``python -m app.workers.session.browser_app``. It holds no database
access and no encryption key: jars arrive sealed to a per-process X25519 key and
leave sealed to the key the broker (or a Runner) supplies with each call.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from dataclasses import dataclass
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
    BROWSER_LOGIN_CANCEL_PATH,
    BROWSER_LOGIN_FINISH_PATH,
    BROWSER_LOGIN_FRAME_PATH,
    BROWSER_LOGIN_INPUT_PATH,
    BROWSER_LOGIN_START_PATH,
    BootstrapRequest,
    BrowserIdentity,
    BrowserOutcome,
    BrowserResult,
    ForgetRequest,
    HeadersRequest,
    HeadersResponse,
    IdentityRequest,
    KeepaliveRequest,
    LoginAction,
    LoginFinished,
    LoginFinishRequest,
    LoginFrame,
    LoginInputRequest,
    LoginRef,
    LoginStarted,
    LoginStartRequest,
    bootstrap_associated_data,
    export_associated_data,
    lease_associated_data,
    login_associated_data,
)
from app.workers.session.login import Frame, LoginError, RemoteLogins
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
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BROWSER_PORT = 19300
# Two sites at a time bounds memory; the broker applies the same limit.
_CONCURRENCY = 2


class BrowserSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    site_session_browser_secret: SecretStr
    site_session_egress_proxy: str | None = None
    site_session_profile_root: Path = Path("/profiles")


class Browser(Protocol):
    async def bootstrap(self, site: str, jar: bytes) -> VisitResult: ...

    async def keepalive(self, site: str) -> VisitResult: ...

    async def headers(self, site: str) -> bytes: ...

    async def forget(self, site: str) -> None: ...


class Logins(Protocol):
    async def start(self, site: str, url: str | None) -> str: ...

    async def frame(self, login_id: str) -> Frame: ...

    async def act(self, login_id: str, actions: Sequence[LoginAction]) -> None: ...

    async def finish(self, login_id: str) -> tuple[str, bytes]: ...

    async def cancel(self, login_id: str) -> None: ...

    async def sweep(self) -> None: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Services:
    browser: Browser
    logins: Logins


type BrowserFactory = Callable[[], AbstractAsyncContextManager[Services]]

_LOGIN_STATUS = {
    "login_not_found": 404,
    "login_busy": 409,
    "login_incomplete": 409,
    "login_url_invalid": 422,
}
_SWEEP_SECONDS = 30


def create_app(*, browser_factory: BrowserFactory, secret: bytes) -> FastAPI:
    verifier = authenticator(secret)
    identity = X25519PrivateKey.generate()
    slots = asyncio.Semaphore(_CONCURRENCY)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with browser_factory() as services:
            app.state.browser = services.browser
            app.state.logins = services.logins

            async def sweep() -> None:
                while True:
                    await asyncio.sleep(_SWEEP_SECONDS)
                    await services.logins.sweep()

            sweeper = asyncio.create_task(sweep())
            try:
                yield
            finally:
                sweeper.cancel()
                with suppress(asyncio.CancelledError):
                    await sweeper
                await services.logins.close()

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

    def logins_of(request: Request) -> Logins:
        return request.app.state.logins  # type: ignore[no-any-return]

    @asynccontextmanager
    async def login_errors() -> AsyncIterator[None]:
        try:
            async with asyncio.timeout(OPERATION_TIMEOUT_SECONDS):
                yield
        except LoginError as exc:
            raise HTTPException(_LOGIN_STATUS.get(exc.code, 409), exc.code) from None
        except (SealError, ValueError, InvalidSessionSite):
            raise HTTPException(422, "invalid_request") from None
        except (TimeoutError, PlaywrightError, OSError):
            raise HTTPException(503, "browser_unavailable") from None

    @app.post(BROWSER_LOGIN_START_PATH, response_model=LoginStarted)
    async def login_start(request: Request) -> LoginStarted:
        body = await verified_model(request, verifier, LoginStartRequest)
        async with login_errors():
            login_id = await logins_of(request).start(body.site, body.url)
        return LoginStarted(login_id=login_id, site=body.site)

    @app.post(BROWSER_LOGIN_FRAME_PATH, response_model=LoginFrame)
    async def login_frame(request: Request) -> LoginFrame:
        body = await verified_model(request, verifier, LoginRef)
        async with login_errors():
            frame = await logins_of(request).frame(body.login_id)
        return LoginFrame(
            image=encode(frame.image), host=frame.host, logged_in=frame.logged_in
        )

    @app.post(BROWSER_LOGIN_INPUT_PATH, status_code=204)
    async def login_input(request: Request) -> Response:
        body = await verified_model(request, verifier, LoginInputRequest)
        async with login_errors():
            await logins_of(request).act(body.login_id, body.actions)
        return Response(status_code=204)

    @app.post(BROWSER_LOGIN_FINISH_PATH, response_model=LoginFinished)
    async def login_finish(request: Request) -> LoginFinished:
        body = await verified_model(request, verifier, LoginFinishRequest)
        async with login_errors():
            reply = decode_public_key(body.reply_key)
            site, jar = await logins_of(request).finish(body.login_id)
        sealed = seal(
            jar, reply, associated_data=login_associated_data(site, body.login_id)
        )
        return LoginFinished(site=site, jar=encode(sealed))

    @app.post(BROWSER_LOGIN_CANCEL_PATH, status_code=204)
    async def login_cancel(request: Request) -> Response:
        body = await verified_model(request, verifier, LoginRef)
        async with login_errors():
            await logins_of(request).cancel(body.login_id)
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
    async def browser_factory() -> AsyncIterator[Services]:
        root = settings.site_session_profile_root
        async with async_playwright() as playwright:
            browser = SiteBrowser(
                playwright, root, proxy=settings.site_session_egress_proxy
            )
            logins = RemoteLogins(browser, root)
            logins.discard_leftovers()
            yield Services(browser, logins)

    app = create_app(
        browser_factory=browser_factory,
        secret=settings.site_session_browser_secret.get_secret_value().encode(),
    )
    uvicorn.run(app, host="0.0.0.0", port=BROWSER_PORT, access_log=False)


if __name__ == "__main__":
    main()
