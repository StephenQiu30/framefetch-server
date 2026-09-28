"""The broker's view of the session browser: a port and its signed HTTP adapter."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

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
    login_associated_data,
)
from app.workers.session.rpc import RpcError, SignedClient
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
from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class BrowserReport:
    outcome: BrowserOutcome
    error_code: str | None = None
    jar: bytes | None = None


class SessionBrowser(Protocol):
    async def bootstrap(
        self, site: str, seed_revision: int, jar: bytes
    ) -> BrowserReport: ...

    async def keepalive(self, site: str, seed_revision: int) -> BrowserReport: ...

    async def headers(
        self,
        site: str,
        seed_revision: int,
        *,
        task_id: str,
        expires_at: int,
        runner_key: bytes,
    ) -> bytes: ...

    async def forget(self, site: str) -> None: ...

    async def login_start(self, site: str, url: str | None) -> LoginStarted: ...

    async def login_frame(self, login_id: str) -> LoginFrame: ...

    async def login_input(
        self, login_id: str, actions: Sequence[LoginAction]
    ) -> None: ...

    async def login_finish(self, login_id: str) -> tuple[str, bytes]: ...

    async def login_cancel(self, login_id: str) -> None: ...


class BrowserUnavailable(Exception):
    """The browser could not be reached or answered outside the contract."""


class LoginRejected(Exception):
    """The browser refused a login request; ``code`` is safe to show."""

    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class HttpSessionBrowser:
    def __init__(self, client: SignedClient) -> None:
        self._client = client

    async def bootstrap(
        self, site: str, seed_revision: int, jar: bytes
    ) -> BrowserReport:
        # Fetch the key per bootstrap: a restarted browser has a new process key.
        identity = await self._call(
            BROWSER_IDENTITY_PATH, IdentityRequest(), BrowserIdentity
        )
        reply = X25519PrivateKey.generate()
        try:
            sealed = seal(
                jar,
                decode_public_key(identity.public_key),
                associated_data=bootstrap_associated_data(site, seed_revision),
            )
        except SealError as exc:
            raise BrowserUnavailable("browser identity is invalid") from exc
        result = await self._call(
            BROWSER_BOOTSTRAP_PATH,
            BootstrapRequest(
                site=site,
                seed_revision=seed_revision,
                jar=encode(sealed),
                reply_key=encode(public_key(reply)),
            ),
            BrowserResult,
        )
        return _report(result, reply, site, seed_revision)

    async def keepalive(self, site: str, seed_revision: int) -> BrowserReport:
        reply = X25519PrivateKey.generate()
        result = await self._call(
            BROWSER_KEEPALIVE_PATH,
            KeepaliveRequest(
                site=site,
                seed_revision=seed_revision,
                reply_key=encode(public_key(reply)),
            ),
            BrowserResult,
        )
        return _report(result, reply, site, seed_revision)

    async def headers(
        self,
        site: str,
        seed_revision: int,
        *,
        task_id: str,
        expires_at: int,
        runner_key: bytes,
    ) -> bytes:
        response = await self._call(
            BROWSER_HEADERS_PATH,
            HeadersRequest(
                site=site,
                seed_revision=seed_revision,
                task_id=task_id,
                expires_at=expires_at,
                public_key=encode(runner_key),
            ),
            HeadersResponse,
        )
        # Sealed by the browser directly to the Runner; the broker only relays it.
        return decode(response.headers)

    async def forget(self, site: str) -> None:
        try:
            await self._client.post_empty(BROWSER_FORGET_PATH, ForgetRequest(site=site))
        except RpcError as exc:
            raise BrowserUnavailable(exc.code) from exc

    async def login_start(self, site: str, url: str | None) -> LoginStarted:
        return await self._login(
            BROWSER_LOGIN_START_PATH,
            LoginStartRequest(site=site, url=url),
            LoginStarted,
        )

    async def login_frame(self, login_id: str) -> LoginFrame:
        return await self._login(
            BROWSER_LOGIN_FRAME_PATH, LoginRef(login_id=login_id), LoginFrame
        )

    async def login_input(self, login_id: str, actions: Sequence[LoginAction]) -> None:
        await self._login(
            BROWSER_LOGIN_INPUT_PATH,
            LoginInputRequest(login_id=login_id, actions=tuple(actions)),
            None,
        )

    async def login_finish(self, login_id: str) -> tuple[str, bytes]:
        reply = X25519PrivateKey.generate()
        finished = await self._login(
            BROWSER_LOGIN_FINISH_PATH,
            LoginFinishRequest(login_id=login_id, reply_key=encode(public_key(reply))),
            LoginFinished,
        )
        try:
            jar = open_sealed(
                decode(finished.jar),
                reply,
                associated_data=login_associated_data(finished.site, login_id),
            )
        except SealError as exc:
            raise BrowserUnavailable("browser returned an unreadable jar") from exc
        return finished.site, jar

    async def login_cancel(self, login_id: str) -> None:
        await self._login(BROWSER_LOGIN_CANCEL_PATH, LoginRef(login_id=login_id), None)

    async def _login[T: BaseModel](
        self, path: str, body: BaseModel, response: type[T] | None
    ) -> T:
        try:
            if response is None:
                await self._client.post_empty(path, body)
                return None  # type: ignore[return-value]
            return await self._client.post(path, body, response)
        except RpcError as exc:
            if 400 <= exc.status < 500 and (
                exc.code.startswith("login_") or exc.code == "invalid_request"
            ):
                raise LoginRejected(exc.code, exc.status) from exc
            raise BrowserUnavailable(exc.code) from exc

    async def _call[T: BrowserIdentity | BrowserResult | HeadersResponse](
        self,
        path: str,
        body: IdentityRequest | BootstrapRequest | KeepaliveRequest | HeadersRequest,
        response: type[T],
    ) -> T:
        try:
            return await self._client.post(path, body, response)
        except RpcError as exc:
            raise BrowserUnavailable(exc.code) from exc


def _report(
    result: BrowserResult, reply: X25519PrivateKey, site: str, seed_revision: int
) -> BrowserReport:
    if result.jar is None:
        return BrowserReport(result.outcome, result.error_code)
    try:
        jar = open_sealed(
            decode(result.jar),
            reply,
            associated_data=export_associated_data(site, seed_revision),
        )
    except SealError as exc:
        raise BrowserUnavailable("browser returned an unreadable jar") from exc
    return BrowserReport(result.outcome, result.error_code, jar)
