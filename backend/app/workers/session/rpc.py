"""HMAC-authenticated JSON RPC shared by the session broker and browser source.

Two independent secrets keep the channels apart: Runners can ask the broker for
leases but cannot use their RPC secret to authenticate to the browser source.
"""

from __future__ import annotations

import secrets
import time
from typing import Final

import httpx
from app.workers.runner.signing import (
    HmacRequestAuthenticator,
    InMemoryNonceGuard,
    RequestAuthenticationError,
    sign_request,
)
from fastapi import HTTPException, Request
from pydantic import BaseModel, ValidationError

TIMESTAMP_HEADER: Final = "X-Session-Timestamp"
NONCE_HEADER: Final = "X-Session-Nonce"
SIGNATURE_HEADER: Final = "X-Session-Signature"
MAX_REQUEST_BYTES: Final = 3 * 1024**2
_SIGNATURE_MAX_AGE: Final = 60
_SIGNATURE_SKEW: Final = 5


class RpcError(Exception):
    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def authenticator(secret: bytes) -> HmacRequestAuthenticator:
    return HmacRequestAuthenticator(
        secret,
        nonce_guard=InMemoryNonceGuard(
            ttl_seconds=_SIGNATURE_MAX_AGE + _SIGNATURE_SKEW + 60, max_entries=20_000
        ),
        max_age_seconds=_SIGNATURE_MAX_AGE,
        max_future_skew_seconds=_SIGNATURE_SKEW,
    )


async def verified_model[ModelT: BaseModel](
    request: Request, verifier: HmacRequestAuthenticator, model: type[ModelT]
) -> ModelT:
    if request.url.query:
        raise HTTPException(400, "invalid_request")
    body = await request.body()
    if len(body) > MAX_REQUEST_BYTES:
        raise HTTPException(413, "request_too_large")
    try:
        verifier.verify(
            request.method,
            request.url.path,
            body,
            int(request.headers.get(TIMESTAMP_HEADER, "")),
            request.headers.get(NONCE_HEADER, ""),
            request.headers.get(SIGNATURE_HEADER, ""),
            now=int(time.time()),
        )
    except (RequestAuthenticationError, ValueError):
        raise HTTPException(401, "invalid_signature") from None
    try:
        return model.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, "invalid_request") from None


class SignedClient:
    """Signs every request; the caller owns the ``httpx.AsyncClient`` lifecycle."""

    def __init__(self, client: httpx.AsyncClient, secret: bytes) -> None:
        self._client = client
        self._secret = secret

    async def post[ModelT: BaseModel](
        self, path: str, body: BaseModel, response: type[ModelT]
    ) -> ModelT:
        raw = await self._send("POST", path, body.model_dump_json().encode())
        try:
            return response.model_validate_json(raw)
        except ValidationError:
            raise RpcError("invalid_response", 502) from None

    async def _send(self, method: str, path: str, body: bytes) -> bytes:
        timestamp, nonce = int(time.time()), secrets.token_urlsafe(24)
        headers = {
            "Content-Type": "application/json",
            TIMESTAMP_HEADER: str(timestamp),
            NONCE_HEADER: nonce,
            SIGNATURE_HEADER: sign_request(
                self._secret, method, path, body, timestamp, nonce
            ),
        }
        try:
            reply = await self._client.request(
                method, path, content=body, headers=headers
            )
        except httpx.HTTPError:
            raise RpcError("rpc_unavailable", 503) from None
        if reply.is_success:
            return reply.content
        code = "rpc_failed"
        try:
            detail = reply.json().get("detail")
            if isinstance(detail, str) and detail.isascii() and len(detail) <= 64:
                code = detail
        except ValueError:
            pass
        raise RpcError(code, reply.status_code)
