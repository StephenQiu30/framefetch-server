import httpx
import pytest
from app.workers.session.rpc import (
    NONCE_HEADER,
    RpcError,
    SignedClient,
    authenticator,
    verified_model,
)
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

SECRET = b"s" * 32


class Echo(BaseModel):
    value: str


def app() -> FastAPI:
    verifier = authenticator(SECRET)
    api = FastAPI()

    @api.post("/echo")
    async def echo(request: Request) -> Echo:
        body = await verified_model(request, verifier, Echo)
        if body.value == "busy":
            raise HTTPException(409, "provider_session_not_ready")
        return body

    return api


def client(secret: bytes = SECRET, api: FastAPI | None = None) -> SignedClient:
    transport = httpx.ASGITransport(app=api or app())
    return SignedClient(
        httpx.AsyncClient(transport=transport, base_url="http://t"), secret
    )


async def test_signed_round_trip_and_error_codes():
    signed = client()
    assert (await signed.post("/echo", Echo(value="hi"), Echo)).value == "hi"
    with pytest.raises(RpcError) as error:
        await signed.post("/echo", Echo(value="busy"), Echo)
    assert (error.value.code, error.value.status) == ("provider_session_not_ready", 409)


async def test_wrong_secret_replay_and_tampering_are_rejected():
    api = app()
    with pytest.raises(RpcError) as error:
        await client(b"x" * 32, api).post("/echo", Echo(value="hi"), Echo)
    assert error.value.status == 401

    transport = httpx.ASGITransport(app=api)
    captured: list[httpx.Request] = []

    async def record(request: httpx.Request) -> None:
        captured.append(request)

    raw = httpx.AsyncClient(
        transport=transport, base_url="http://t", event_hooks={"request": [record]}
    )
    await SignedClient(raw, SECRET).post("/echo", Echo(value="hi"), Echo)
    original = captured[0]
    replay = await raw.post("/echo", content=original.content, headers=original.headers)
    assert replay.status_code == 401
    headers = dict(original.headers)
    headers[NONCE_HEADER] = "a" * 24
    tampered = await raw.post("/echo", content=b'{"value":"evil"}', headers=headers)
    assert tampered.status_code == 401


async def test_unreachable_peer_is_unavailable():
    async def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    raw = httpx.AsyncClient(transport=httpx.MockTransport(fail), base_url="http://t")
    with pytest.raises(RpcError) as error:
        await SignedClient(raw, SECRET).post("/echo", Echo(value="hi"), Echo)
    assert (error.value.code, error.value.status) == ("rpc_unavailable", 503)
