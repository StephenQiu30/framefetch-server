"""Offline account bridge checks using ASGI/Fake extension traffic only."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from app.core.config import CookieSourceSettings
from app.workers.identity import cookie_source as m
from app.workers.identity.extension import extension_origin
from app.workers.identity.yuanbao_account import (
    YUANBAO_ORIGIN,
    stable_yuanbao_account_digest,
    validate_yuanbao_account_payload,
)
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

TOKEN = "synthetic-test-only-runner-token-32-bytes"
KEY = "synthetic-test-only-pairing-key-32-bytes"
PAYLOAD = {
    "origin": YUANBAO_ORIGIN,
    "account_id": "synthetic-account",
    "auth_token": "synthetic-account-token",
}


def settings():
    return CookieSourceSettings(
        cookie_source_token=SecretStr(TOKEN), cookie_source_pairing_key=SecretStr(KEY)
    )


def request(site="wechat_channels", seconds=30):
    return m.CookieRequest(
        site=site,
        task_id="task",
        deadline=datetime.now(UTC) + timedelta(seconds=seconds),
    )


def authenticate(ws):
    challenge = ws.receive_json()
    own = "a" * 64
    ws.send_json({"type": "challenge", "nonce": own})
    assert ws.receive_json() == {
        "type": "proof",
        "proof": m.proof(KEY, "server", own, challenge["nonce"]),
    }
    ws.send_json(
        {
            "type": "proof",
            "proof": m.proof(KEY, "extension", challenge["nonce"], own),
            "version": "1.0.0",
        }
    )
    assert ws.receive_json() == {"type": "ready"}


@pytest.fixture
def source():
    service = m.CookieSource(settings())
    service.connection = AsyncMock()
    state = {"account": PAYLOAD.copy()}

    async def send(ws, message):
        assert set(message) == {"type", "request_id", "site", "deadline"}
        assert message["type"] == "yuanbao_account"
        assert message["site"] == "wechat_channels"
        service._pending[message["request_id"]].set_result(state["account"])

    service.send = AsyncMock(side_effect=send)
    return service, state


async def test_operation_local_account_response_and_stable_hmac(source):
    service, state = source
    first_request = request()
    first = await service.yuanbao_account(first_request)
    assert first == {
        **PAYLOAD,
        "kind": "yuanbao_account",
        "digest": stable_yuanbao_account_digest(
            validate_yuanbao_account_payload(PAYLOAD), site="wechat_channels", key=TOKEN
        ),
        "local_use_deadline": first_request.deadline.isoformat(),
    }
    second = await service.yuanbao_account(request(seconds=60))
    assert second["digest"] == first["digest"]
    assert second["local_use_deadline"] != first["local_use_deadline"]
    for field in ("account_id", "auth_token"):
        state["account"] = {**PAYLOAD, field: "different-account-material"}
        assert (await service.yuanbao_account(request()))["digest"] != first["digest"]
    assert service.send.await_count == 4
    assert (
        not service._pending and not service._pending_kinds and service._requests == 0
    )


@pytest.mark.parametrize("site", ["instagram", "youtube", "unknown_site"])
async def test_fixed_site_and_cookie_route_refuse_page_source_without_read(
    source, site
):
    service, _ = source
    with pytest.raises(m.IdentityUnavailable, match="identity_source_mismatch"):
        await service.yuanbao_account(request(site))
    with pytest.raises(m.IdentityUnavailable, match="identity_source_mismatch"):
        await service.cookies(request())
    service.send.assert_not_called()


async def test_independent_registry_origin_declaration_required(source, monkeypatch):
    from dataclasses import replace

    service, _ = source
    original = m.provider_profile_for_key("wechat_channels")
    for profile in (
        replace(original, identity_source="cookies"),
        replace(original, identity_origin="https://lookalike.invalid"),
    ):
        monkeypatch.setattr(
            m, "provider_profile_for_key", lambda site, selected=profile: selected
        )
        with pytest.raises(m.IdentityUnavailable, match="identity_source_mismatch"):
            await service.yuanbao_account(request())
    service.send.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {**PAYLOAD, "origin": "https://yuanbao.tencent.com.evil.invalid"},
        {**PAYLOAD, "auth_token": "synthetic-private-secret\n"},
        {**PAYLOAD, "account_id": "界" * 342},
        {**PAYLOAD, "auth_token": "x" * 8193},
        {**PAYLOAD, "auth_token": 42},
        {**PAYLOAD, "signature": "synthetic-private-secret"},
        {**PAYLOAD, "cookies": "synthetic-private-secret"},
    ],
)
async def test_account_validation_returns_fixed_cause_without_input(source, payload):
    service, state = source
    state["account"] = payload
    with pytest.raises(m.IdentityUnavailable) as caught:
        await service.yuanbao_account(request())
    assert str(caught.value) == "identity_material_invalid"
    assert (
        not service._pending and not service._pending_kinds and service._requests == 0
    )


async def test_disconnect_timeout_cancel_and_cookie_concurrency_release_all_state(
    source, monkeypatch
):
    service, _ = source
    socket = service.connection
    service.connection = None
    with pytest.raises(m.IdentityUnavailable, match="extension_disconnected"):
        await service.yuanbao_account(request())
    with pytest.raises(m.IdentityUnavailable, match="identity_deadline_invalid"):
        await service.yuanbao_account(request(seconds=0))
    service.connection = socket
    service.send = AsyncMock()
    monkeypatch.setattr(m, "REQUEST_TIMEOUT", 0.01)
    with pytest.raises(m.IdentityUnavailable, match="extension_timeout"):
        await service.yuanbao_account(request())
    assert (
        not service._pending and not service._pending_kinds and service._requests == 0
    )
    monkeypatch.setattr(m, "REQUEST_TIMEOUT", 5)
    task = asyncio.create_task(service.yuanbao_account(request()))
    await asyncio.sleep(0)
    with pytest.raises(m.IdentityUnavailable, match="extension_timeout"):
        await service.cookies(request("instagram"))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (
        not service._pending and not service._pending_kinds and service._requests == 0
    )
    task = asyncio.create_task(service.yuanbao_account(request()))
    await asyncio.sleep(0)
    service.disconnected(socket)
    with pytest.raises(m.IdentityUnavailable, match="extension_disconnected"):
        await task
    assert (
        not service._pending and not service._pending_kinds and service._requests == 0
    )


async def test_cancelled_request_late_account_response_cannot_complete_next_request(
    source,
):
    service, _ = source
    service.send = AsyncMock()
    cancelled = asyncio.create_task(service.yuanbao_account(request()))
    await asyncio.sleep(0)
    old_id = next(iter(service._pending))
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    assert (
        not service._pending and not service._pending_kinds and service._requests == 0
    )
    active = asyncio.create_task(service.yuanbao_account(request()))
    await asyncio.sleep(0)
    new_id = next(iter(service._pending))
    assert new_id != old_id
    incoming = asyncio.Queue()
    received = asyncio.Event()

    async def receive_text():
        message = await incoming.get()
        received.set()
        return json.dumps(message)

    socket = AsyncMock()
    socket.receive_text.side_effect = receive_text
    responses = asyncio.create_task(service._responses(socket))
    try:
        await incoming.put({"type": "yuanbao_account", "request_id": old_id, **PAYLOAD})
        await received.wait()
        assert not active.done()
        assert set(service._pending) == {new_id}
        await incoming.put({"type": "yuanbao_account", "request_id": new_id, **PAYLOAD})
        result = await active
        assert result["auth_token"] == PAYLOAD["auth_token"]
        assert (
            not service._pending
            and not service._pending_kinds
            and service._requests == 0
        )
    finally:
        responses.cancel()
        with pytest.raises(asyncio.CancelledError):
            await responses


@pytest.mark.parametrize("expire_at", [2, 3])
async def test_account_response_at_deadline_is_rejected(source, monkeypatch, expire_at):
    service, _ = source
    operation = request()
    real_now = datetime.now(UTC)

    class Clock:
        calls = 0

        @classmethod
        def now(cls, zone):
            cls.calls += 1
            return operation.deadline if cls.calls >= expire_at else real_now

    monkeypatch.setattr(m, "datetime", Clock)
    with pytest.raises(m.IdentityUnavailable, match="identity_deadline_invalid"):
        await service.yuanbao_account(operation)
    assert not service._pending and not service._pending_kinds


async def test_private_http_response_not_cached_and_errors_never_serialize_account():
    app = m.create_app(settings())
    source = app.state.cookie_source
    source.connection = AsyncMock()

    async def send(ws, message):
        source._pending[message["request_id"]].set_result(
            {**PAYLOAD, "auth_token": "synthetic-private-secret\n"}
        )

    source.send = AsyncMock(side_effect=send)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://host",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as client:
        assert (
            await client.post("/yuanbao-account", content=b"x" * 4097)
        ).status_code == 413
        invalid = await client.post(
            "/yuanbao-account", json={"site": "synthetic-private-secret"}
        )
        assert invalid.status_code == 422
        assert "synthetic-private-secret" not in invalid.text
        response = await client.post(
            "/yuanbao-account", json=request().model_dump(mode="json")
        )
    assert response.status_code == 503
    assert response.json() == {"cause": "identity_material_invalid"}
    assert response.headers["cache-control"] == "no-store"
    assert "synthetic-private-secret" not in response.text


def test_authenticated_account_request_id_and_timeout_late_response(monkeypatch):
    monkeypatch.setattr(m, "REQUEST_TIMEOUT", 0.1)
    with TestClient(m.create_app(settings())) as client:
        with client.websocket_connect(
            "/extension", headers={"Origin": extension_origin()}
        ) as ws:
            authenticate(ws)
            with ThreadPoolExecutor() as pool:

                def submit():
                    return pool.submit(
                        client.post,
                        "/yuanbao-account",
                        json=request().model_dump(mode="json"),
                        headers={"Authorization": f"Bearer {TOKEN}"},
                    )

                expired = submit()
                old = ws.receive_json()
                assert expired.result(timeout=2).json() == {
                    "cause": "extension_timeout"
                }
                active = submit()
                current = ws.receive_json()
                assert set(current) == {"type", "request_id", "site", "deadline"}
                assert current["site"] == "wechat_channels"
                assert current["request_id"] != old["request_id"]
                ws.send_json(
                    {
                        "type": "yuanbao_account",
                        "request_id": old["request_id"],
                        **PAYLOAD,
                    }
                )
                ws.send_json({"type": "ping"})
                assert ws.receive_json() == {"type": "pong"}
                assert not active.done()
                ws.send_json(
                    {
                        "type": "yuanbao_account",
                        "request_id": current["request_id"],
                        **PAYLOAD,
                    }
                )
                result = active.result(timeout=2)
                assert result.status_code == 200
                assert result.json()["auth_token"] == PAYLOAD["auth_token"]
                assert result.headers["cache-control"] == "no-store"
                source = client.app.state.cookie_source
                assert not source._pending and not source._pending_kinds


@pytest.mark.parametrize("cause", sorted(m.YUANBAO_READ_CAUSES))
def test_extension_read_failure_fixed_cause_preserves_authenticated_connection(cause):
    with TestClient(m.create_app(settings())) as client:
        with client.websocket_connect(
            "/extension", headers={"Origin": extension_origin()}
        ) as ws:
            authenticate(ws)
            with ThreadPoolExecutor() as pool:
                future = pool.submit(
                    client.post,
                    "/yuanbao-account",
                    json=request().model_dump(mode="json"),
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )
                message = ws.receive_json()
                ws.send_json(
                    {
                        "type": "yuanbao_account",
                        "request_id": message["request_id"],
                        "cause": cause,
                    }
                )
                assert future.result(timeout=2).json() == {"cause": cause}
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}


@pytest.mark.parametrize("response_kind", ["cookies", "unsafe_cause"])
def test_response_type_cannot_cross_pending_kind_or_export_arbitrary_failure(
    response_kind,
):
    with TestClient(m.create_app(settings())) as client:
        with client.websocket_connect(
            "/extension", headers={"Origin": extension_origin()}
        ) as ws:
            authenticate(ws)
            with ThreadPoolExecutor() as pool:
                future = pool.submit(
                    client.post,
                    "/yuanbao-account",
                    json=request().model_dump(mode="json"),
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )
                message = ws.receive_json()
                wrong = (
                    {"type": "cookies", "cookies": []}
                    if response_kind == "cookies"
                    else {
                        "type": "yuanbao_account",
                        "cause": "synthetic-private-secret",
                    }
                )
                ws.send_json({"request_id": message["request_id"], **wrong})
                with pytest.raises(WebSocketDisconnect):
                    ws.receive_json()
                result = future.result(timeout=2)
                assert result.json() == {"cause": "extension_disconnected"}
                assert "synthetic-private-secret" not in result.text
