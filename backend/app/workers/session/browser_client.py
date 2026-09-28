"""The broker's view of the session browser: a port and its signed HTTP adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

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


@dataclass(frozen=True, slots=True)
class BrowserReport:
    outcome: BrowserOutcome
    error_code: str | None = None
    jar: bytes | None = None


class SessionBrowser(Protocol):
    async def identity(self) -> str: ...

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


class BrowserUnavailable(Exception):
    """The browser could not be reached or answered outside the contract."""


class HttpSessionBrowser:
    def __init__(self, client: SignedClient) -> None:
        self._client = client

    async def identity(self) -> str:
        identity = await self._call(
            BROWSER_IDENTITY_PATH, IdentityRequest(), BrowserIdentity
        )
        return identity.public_key

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
