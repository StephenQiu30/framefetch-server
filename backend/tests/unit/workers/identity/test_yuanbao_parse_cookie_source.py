"""Fixed HTTP parse result: authentication, request binding and cleanup."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from app.core.config import CookieSourceSettings
from app.workers.identity import cookie_source as m
from app.workers.identity import yuanbao_parse as parse
from app.workers.identity.extension import extension_origin
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from starlette.websockets import WebSocketDisconnect

TOKEN = "synthetic-test-only-runner-token-32-bytes"
KEY = "synthetic-test-only-pairing-key-32-bytes"
SHARE = "https://weixin.qq.com/sph/SyntheticShare"
PARSE_URL = "https://yuanbao.tencent.com/api/weixin/get_parse_result"
CAPTURED = {
    "request_method": "POST",
    "request_url": PARSE_URL,
    "response_url": PARSE_URL,
    "http_status": 200,
    "request_body": {"type": "video_channel_url", "url": SHARE, "scene": 1},
    "payload": {"code": 0, "data": {"playable_url": "synthetic-reference"}},
}
RESULT = {"account_id": "synthetic-account", "captured": CAPTURED}


def settings():
    return CookieSourceSettings(
        cookie_source_token=SecretStr(TOKEN), cookie_source_pairing_key=SecretStr(KEY)
    )


def request(seconds=120):
    return m.ShareParseRequest(
        site="wechat_channels",
        task_id="task",
        deadline=datetime.now(UTC) + timedelta(seconds=seconds),
        canonical_share_url=SHARE,
    )


def authenticate(ws, key=KEY):
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
            "proof": m.proof(key, "extension", challenge["nonce"], own),
            "version": "1.1.0",
        }
    )
    return ws.receive_json()


@pytest.fixture(autouse=True)
def http_registry(monkeypatch):
    original = m.provider_profile_for_key
    profile = replace(original("wechat_channels"), identity_source="yuanbao_http")
    monkeypatch.setattr(
        m,
        "provider_profile_for_key",
        lambda site: profile if site == "wechat_channels" else original(site),
    )


@pytest.fixture
def source():
    service = m.CookieSource(settings())
    service.connection = AsyncMock()
    state = {"result": deepcopy(RESULT)}

    async def send(ws, message):
        assert set(message) == {
            "type",
            "request_id",
            "site",
            "canonical_share_url",
            "deadline",
        }
        assert message["type"] == "yuanbao_parse"
        assert message["site"] == "wechat_channels"
        assert message["canonical_share_url"] == SHARE
        service._pending[message["request_id"]].set_result(state["result"])

    service.send = AsyncMock(side_effect=send)
    return service, state


async def test_fixed_parse_returns_only_account_digest_and_actual_capture(source):
    service, state = source
    operation = request()
    before = datetime.now(UTC)
    first = await service.yuanbao_parse(operation)
    sent = service.send.await_args.args[1]
    effective = datetime.fromisoformat(sent["deadline"])
    assert before < effective <= before + timedelta(seconds=31)
    assert effective < operation.deadline
    assert set(first) == {"identity_digest", "captured"}
    assert first["captured"] == CAPTURED
    assert len(first["identity_digest"]) == 64
    assert RESULT["account_id"] not in json.dumps(first)
    state["result"]["captured"]["payload"] = {"code": 1}
    second = await service.yuanbao_parse(request(seconds=10))
    assert second["identity_digest"] == first["identity_digest"]
    state["result"]["account_id"] = "another-synthetic-account"
    third = await service.yuanbao_parse(request())
    assert third["identity_digest"] != first["identity_digest"]
    assert not service._pending and not service._pending_kinds
    assert service._requests == 0


@pytest.mark.parametrize(
    "change",
    [
        {"site": "youtube"},
        {"canonical_share_url": "http://weixin.qq.com/sph/SyntheticShare"},
        {"canonical_share_url": "https://weixin.qq.com:443/sph/SyntheticShare"},
        {"canonical_share_url": "https://weixin.qq.com.evil.invalid/sph/Share"},
        {"canonical_share_url": "https://weixin.qq.com/sph/abc"},
        {"canonical_share_url": SHARE + "/"},
        {"canonical_share_url": SHARE + "?token=synthetic"},
        {"canonical_share_url": SHARE + "#fragment"},
        {"canonical_share_url": SHARE + "\n"},
        {"canonical_share_url": "http://127.0.0.1/private"},
        {"canonical_share_url": 1},
        {"task_id": "task\n"},
        {"url": PARSE_URL},
        {"headers": {"Authorization": "synthetic-secret"}},
        {"deadline": datetime.now()},
    ],
)
def test_parse_request_accepts_only_the_fixed_canonical_share(change):
    with pytest.raises(ValidationError):
        m.ShareParseRequest.model_validate({**request().model_dump(), **change})


@pytest.mark.parametrize(
    "change",
    [
        {"identity_source": "cookies"},
        {"identity_source": "yuanbao_account"},
        {"identity_origin": "https://yuanbao.tencent.com.evil.invalid"},
        {"identity": "none"},
        {"identity": "prefer"},
        {"content_scope": "public"},
        {"content_scope": "personal_full"},
        {"cookie_domain_allowlist": ("yuanbao.tencent.com",)},
    ],
)
async def test_registry_declaration_is_required_before_request(
    source, monkeypatch, change
):
    service, _ = source
    profile = replace(m.provider_profile_for_key("wechat_channels"), **change)
    monkeypatch.setattr(m, "provider_profile_for_key", lambda site: profile)
    with pytest.raises(m.IdentityUnavailable, match="identity_source_mismatch"):
        await service.yuanbao_parse(request())
    service.send.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"request_method": "GET"},
        {"request_url": PARSE_URL + "?other=synthetic"},
        {"response_url": "https://evil.invalid/api/weixin/get_parse_result"},
        {"response_url": PARSE_URL + "/"},
        {"http_status": True},
        {"http_status": 200.0},
        {"request_body": {"type": "video_channel_url", "url": SHARE, "scene": True}},
        {"request_body": {"type": "video_channel_url", "url": SHARE, "scene": 1.0}},
        {"request_body": {"type": "video_channel_url", "url": SHARE + "x", "scene": 1}},
        {"payload": []},
        {"payload": {"code": float("nan")}},
        {"headers": {"Authorization": "synthetic-secret"}},
        {"auth_token": "synthetic-secret"},
    ],
)
async def test_capture_binding_and_response_shape_fail_closed(source, change):
    service, state = source
    state["result"]["captured"].update(change)
    with pytest.raises(m.IdentityUnavailable, match="parse_response_invalid"):
        await service.yuanbao_parse(request())
    assert not service._pending and not service._pending_kinds
    assert service._requests == 0


@pytest.mark.parametrize("account", ["", "synthetic\nsecret", "界" * 342, 1])
async def test_account_identifier_never_exports_on_invalid_result(source, account):
    service, state = source
    state["result"]["account_id"] = account
    with pytest.raises(m.IdentityUnavailable, match="parse_response_invalid"):
        await service.yuanbao_parse(request())


async def test_capture_is_bounded_before_any_http_result(source):
    service, state = source
    state["result"]["captured"]["payload"] = {
        "data": "x" * parse.YUANBAO_PARSE_MAX_BYTES
    }
    with pytest.raises(m.IdentityUnavailable, match="parse_response_invalid"):
        await service.yuanbao_parse(request())


async def test_deadline_disconnect_timeout_cancel_and_shared_concurrency(
    source, monkeypatch
):
    service, _ = source
    socket = service.connection
    service.connection = None
    with pytest.raises(m.IdentityUnavailable, match="extension_disconnected"):
        await service.yuanbao_parse(request())
    with pytest.raises(m.IdentityUnavailable, match="identity_deadline_invalid"):
        await service.yuanbao_parse(request(seconds=0))
    service.connection = socket
    service.send = AsyncMock()
    monkeypatch.setattr(m, "YUANBAO_PARSE_TIMEOUT", 0.01)
    with pytest.raises(m.IdentityUnavailable, match="extension_timeout"):
        await service.yuanbao_parse(request())
    assert not service._pending and not service._pending_kinds
    monkeypatch.setattr(m, "YUANBAO_PARSE_TIMEOUT", 30)
    task = asyncio.create_task(service.yuanbao_parse(request()))
    await asyncio.sleep(0)
    with pytest.raises(m.IdentityUnavailable, match="extension_timeout"):
        await service.cookies(
            m.CookieRequest(
                site="instagram", task_id="task", deadline=request().deadline
            )
        )
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not service._pending and not service._pending_kinds
    assert service._requests == 0
    task = asyncio.create_task(service.yuanbao_parse(request()))
    await asyncio.sleep(0)
    service.disconnected(socket)
    with pytest.raises(m.IdentityUnavailable, match="extension_disconnected"):
        await task
    assert not service._pending and not service._pending_kinds
    assert service._requests == 0


@pytest.mark.parametrize("expire_at", [2, 3])
async def test_received_parse_at_deadline_cannot_escape_after_digest(
    source, monkeypatch, expire_at
):
    service, _ = source
    operation = request(seconds=10)
    initial = datetime.now(UTC)

    class Clock:
        calls = 0

        @classmethod
        def now(cls, zone):
            cls.calls += 1
            return operation.deadline if cls.calls >= expire_at else initial

    monkeypatch.setattr(m, "datetime", Clock)
    with pytest.raises(m.IdentityUnavailable, match="identity_deadline_invalid"):
        await service.yuanbao_parse(operation)
    assert not service._pending and not service._pending_kinds
    assert service._requests == 0


async def test_cancelled_request_late_capture_cannot_complete_next_request(source):
    service, _ = source
    service.send = AsyncMock()
    cancelled = asyncio.create_task(service.yuanbao_parse(request()))
    await asyncio.sleep(0)
    old_id = next(iter(service._pending))
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    active = asyncio.create_task(service.yuanbao_parse(request()))
    await asyncio.sleep(0)
    new_id = next(iter(service._pending))
    incoming = asyncio.Queue()
    delivered = asyncio.Event()

    async def receive_text():
        message = await incoming.get()
        delivered.set()
        return json.dumps(message)

    socket = AsyncMock()
    socket.receive_text.side_effect = receive_text
    responses = asyncio.create_task(service._responses(socket))
    try:
        await incoming.put({"type": "yuanbao_parse", "request_id": old_id, **RESULT})
        await delivered.wait()
        assert not active.done()
        await incoming.put({"type": "yuanbao_parse", "request_id": new_id, **RESULT})
        assert (await active)["captured"] == CAPTURED
        assert not service._pending and not service._pending_kinds
        assert service._requests == 0
    finally:
        responses.cancel()
        with pytest.raises(asyncio.CancelledError):
            await responses


async def test_runner_authorization_precedes_body_and_errors_never_export_material():
    app = m.create_app(settings())
    source = app.state.cookie_source
    source.connection = AsyncMock()

    async def send(ws, message):
        source._pending[message["request_id"]].set_result(
            {**RESULT, "account_id": "synthetic-private-secret\n"}
        )

    source.send = AsyncMock(side_effect=send)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://host"
    ) as client:
        denied = await client.post("/yuanbao-parse", content=b"invalid json")
        assert denied.status_code == 401
        source.send.assert_not_called()
        client.headers["Authorization"] = f"Bearer {TOKEN}"
        assert (await client.get("/yuanbao-parse")).status_code == 404
        assert (
            await client.post("/yuanbao-parse", content=b"x" * 4097)
        ).status_code == 413
        invalid = await client.post(
            "/yuanbao-parse", json={"site": "synthetic-private-secret"}
        )
        assert invalid.status_code == 422
        assert "synthetic-private-secret" not in invalid.text
        result = await client.post(
            "/yuanbao-parse", json=request().model_dump(mode="json")
        )
        assert result.status_code == 503
        assert result.json() == {"cause": "parse_response_invalid"}
        assert result.headers["cache-control"] == "no-store"
        assert "synthetic-private-secret" not in result.text


def test_hmac_authentication_precedes_http_requests_and_returns_no_credentials():
    with TestClient(m.create_app(settings())) as client:
        with client.websocket_connect(
            "/extension", headers={"Origin": extension_origin()}
        ) as ws:
            assert authenticate(ws) == {"type": "ready"}
            with ThreadPoolExecutor() as pool:
                future = pool.submit(
                    client.post,
                    "/yuanbao-parse",
                    json=request().model_dump(mode="json"),
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )
                message = ws.receive_json()
                ws.send_json(
                    {
                        "type": "yuanbao_parse",
                        "request_id": message["request_id"],
                        **RESULT,
                    }
                )
                result = future.result(timeout=2)
                assert result.status_code == 200
                assert set(result.json()) == {"identity_digest", "captured"}
                assert RESULT["account_id"] not in result.text
                assert result.headers["cache-control"] == "no-store"
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}


@pytest.mark.parametrize("response_kind", ["cookies", "unsafe_cause", "extra_secret"])
def test_response_kind_and_fixed_failure_cannot_cross_the_pending_request(
    response_kind,
):
    with TestClient(m.create_app(settings())) as client:
        with client.websocket_connect(
            "/extension", headers={"Origin": extension_origin()}
        ) as ws:
            assert authenticate(ws) == {"type": "ready"}
            with ThreadPoolExecutor() as pool:
                future = pool.submit(
                    client.post,
                    "/yuanbao-parse",
                    json=request().model_dump(mode="json"),
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )
                message = ws.receive_json()
                wrong = (
                    {"type": "cookies", "cookies": []}
                    if response_kind == "cookies"
                    else {"type": "yuanbao_parse", "cause": "synthetic-private-secret"}
                    if response_kind == "unsafe_cause"
                    else {
                        "type": "yuanbao_parse",
                        **RESULT,
                        "auth_token": "synthetic-private-secret",
                    }
                )
                ws.send_json({"request_id": message["request_id"], **wrong})
                with pytest.raises(WebSocketDisconnect):
                    ws.receive_json()
                result = future.result(timeout=2)
                assert result.json() == {"cause": "extension_disconnected"}
                assert "synthetic-private-secret" not in result.text


@pytest.mark.parametrize("cause", sorted(m.YUANBAO_PARSE_CAUSES))
def test_fixed_http_failure_preserves_authenticated_connection(cause):
    with TestClient(m.create_app(settings())) as client:
        with client.websocket_connect(
            "/extension", headers={"Origin": extension_origin()}
        ) as ws:
            assert authenticate(ws) == {"type": "ready"}
            with ThreadPoolExecutor() as pool:
                future = pool.submit(
                    client.post,
                    "/yuanbao-parse",
                    json=request().model_dump(mode="json"),
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )
                message = ws.receive_json()
                ws.send_json(
                    {
                        "type": "yuanbao_parse",
                        "request_id": message["request_id"],
                        "cause": cause,
                    }
                )
                assert future.result(timeout=2).json() == {"cause": cause}
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}


@pytest.mark.parametrize(
    "wire",
    [
        '{"type":"yuanbao_parse","type":"cookies"}',
        '{"type":"yuanbao_parse","payload":{"data":NaN}}',
        '{"type":"yuanbao_parse","request_id":"first","request_id":"second"}',
        '{"type":"cookies","cookies":[],"padding":"' + "x" * m.MAX_COOKIE_BYTES + '"}',
        '{"type":"yuanbao_parse","padding":"'
        + "x" * m.YUANBAO_PARSE_MAX_MESSAGE_BYTES
        + '"}',
    ],
)
async def test_bridge_json_has_one_meaning_and_kind_specific_size_limit(wire):
    socket = AsyncMock()
    socket.receive_text.return_value = wire
    with pytest.raises(ValueError):
        await m.receive(socket, allow_yuanbao_parse=True)


async def test_http_frame_can_exceed_cookie_cap_within_its_own_bounded_limit():
    socket = AsyncMock()
    message = {
        "type": "yuanbao_parse",
        "payload": {"data": "x" * (m.MAX_COOKIE_BYTES + 1)},
    }
    socket.receive_text.return_value = json.dumps(message)
    assert await m.receive(socket, allow_yuanbao_parse=True) == message
    with pytest.raises(ValueError):
        await m.receive(socket)


@pytest.mark.parametrize(
    "change",
    [
        {"identity_digest": "invalid"},
        {"identity_digest": "a" * 64 + "\n"},
        {"account_id": "synthetic-secret"},
        {"auth_token": "synthetic-secret"},
        {"captured": {**CAPTURED, "response_url": PARSE_URL + "?token=synthetic"}},
    ],
)
def test_runner_result_validator_accepts_only_the_bound_public_shape(change):
    raw = {"identity_digest": "a" * 64, "captured": CAPTURED, **change}
    with pytest.raises(ValueError):
        parse.validate_yuanbao_parse_result(raw, canonical_share_url=SHARE)


def test_runner_result_validator_binds_capture_to_the_submitted_share():
    raw = {"identity_digest": "a" * 64, "captured": CAPTURED}
    valid = parse.validate_yuanbao_parse_result(raw, canonical_share_url=SHARE)
    assert valid.captured.request_body.url == SHARE
    with pytest.raises(ValueError, match="response share mismatch"):
        parse.validate_yuanbao_parse_result(raw, canonical_share_url=SHARE + "x")
