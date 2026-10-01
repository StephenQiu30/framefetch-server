"""Live bridge authentication, request ownership and account digest."""

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from app.core.config import CookieSourceSettings
from app.workers.identity import cookie_source as m
from app.workers.identity.extension import extension_origin
from app.workers.runner.errors import RunnerFailure
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from starlette.websockets import WebSocketDisconnect

TOKEN = "synthetic-test-only-runner-token-32-bytes"
KEY = "synthetic-test-only-pairing-key-32-bytes"
COOKIE = dict(
    domain=".instagram.com",
    path="/",
    name="sessionid",
    value="synthetic",
    secure=True,
    httpOnly=True,
    hostOnly=False,
)


def settings():
    return CookieSourceSettings(
        cookie_source_token=SecretStr(TOKEN), cookie_source_pairing_key=SecretStr(KEY)
    )


def request(site="instagram", seconds=30):
    return m.CookieRequest(
        site=site,
        task_id="task",
        deadline=datetime.now(UTC) + timedelta(seconds=seconds),
    )


def authenticate(ws, key=KEY):
    challenge = ws.receive_json()
    own = "a" * 64
    ws.send_json(dict(type="challenge", nonce=own))
    assert ws.receive_json() == dict(
        type="proof", proof=m.proof(KEY, "server", own, challenge["nonce"])
    )
    ws.send_json(
        dict(
            type="proof",
            proof=m.proof(key, "extension", challenge["nonce"], own),
            version="1.0.0",
        )
    )
    return ws.receive_json()


@pytest.fixture
def source():
    service = m.CookieSource(settings())
    service.connection = AsyncMock()
    state = {"cookies": [COOKIE.copy()]}

    async def send(ws, message):
        assert set(message) == {"type", "request_id", "domains"}
        service._pending[message["request_id"]].set_result(state["cookies"])

    service.send = AsyncMock(side_effect=send)
    return service, state


async def test_live_requests_stable_digest_expiry_and_visitor_filter(source):
    service, state = source
    first = await service.cookies(request())
    state["cookies"] = [
        {**COOKIE, "name": "visitor", "value": "changed"},
        {**COOKIE, "expirationDate": datetime.now(UTC).timestamp() + 9999},
        {**COOKIE, "name": "expired", "expirationDate": 1},
    ]
    second = await service.cookies(request())
    assert first["digest"] == second["digest"]
    assert b"expired" not in base64.b64decode(second["cookies"])
    state["cookies"] = [{**COOKIE, "value": "another-account"}]
    assert (await service.cookies(request()))["digest"] != first["digest"]
    assert service.send.await_count == 3 and not service._pending


@pytest.mark.parametrize(
    "cookies", [[], [{**COOKIE, "name": "visitor"}], [{**COOKIE, "expirationDate": 1}]]
)
async def test_missing_account(source, cookies):
    service, state = source
    state["cookies"] = cookies
    with pytest.raises(m.IdentityUnavailable, match="credential_missing"):
        await service.cookies(request())


async def test_qq_requires_both_account_fields(source):
    service, state = source
    state["cookies"] = [
        {**COOKIE, "domain": ".v.qq.com", "name": name}
        for name in ("v_vuserid", "v_vusession")
    ]
    assert (await service.cookies(request("qqvideo")))["digest"]
    state["cookies"].pop()
    with pytest.raises(m.IdentityUnavailable, match="credential_missing"):
        await service.cookies(request("qqvideo"))


@pytest.mark.parametrize(
    "cookie",
    [
        {**COOKIE, "domain": "evilinstagram.com"},
        {**COOKIE, "partitionKey": {}},
        {**COOKIE, "value": "unsafe\nvalue"},
        {**COOKIE, "expirationDate": float("inf")},
    ],
)
async def test_bad_material_refused(source, cookie):
    service, state = source
    state["cookies"] = [cookie]
    with pytest.raises((ValidationError, RunnerFailure)):
        await service.cookies(request())
    assert not service._pending


@pytest.mark.parametrize(
    "site,cause",
    [
        ("tiktok", "identity_not_declared"),
        ("hongguo_web", "identity_cookie_rules_unverified"),
        ("wechat_channels", "identity_cookie_rules_unverified"),
    ],
)
async def test_undeclared_or_unverified_rules_never_read(source, site, cause):
    service, _ = source
    with pytest.raises(m.IdentityUnavailable, match=cause):
        await service.cookies(request(site))
    service.send.assert_not_called()


async def test_disconnected_deadline_timeout_cancellation_and_concurrency(
    source, monkeypatch
):
    service, _ = source
    socket = service.connection
    service.connection = None
    with pytest.raises(m.IdentityUnavailable, match="extension_disconnected"):
        await service.cookies(request())
    with pytest.raises(m.IdentityUnavailable, match="identity_deadline_invalid"):
        await service.cookies(request(seconds=0))
    service.connection = socket
    service.send = AsyncMock()
    monkeypatch.setattr(m, "REQUEST_TIMEOUT", 0.01)
    with pytest.raises(m.IdentityUnavailable, match="extension_timeout"):
        await service.cookies(request())
    assert not service._pending and service._requests == 0
    monkeypatch.setattr(m, "REQUEST_TIMEOUT", 5)
    task = asyncio.create_task(service.cookies(request()))
    await asyncio.sleep(0)
    with pytest.raises(m.IdentityUnavailable, match="extension_timeout"):
        await service.cookies(request())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not service._pending and service._requests == 0
    task = asyncio.create_task(service.cookies(request()))
    await asyncio.sleep(0)
    service.disconnected(socket)
    with pytest.raises(m.IdentityUnavailable, match="extension_disconnected"):
        await task


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Basic arbitrary"])
async def test_bearer_required_before_parsing(authorization):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=m.create_app(settings())),
        base_url="http://host",
    ) as client:
        response = await client.post(
            "/cookies",
            content=b"not-json",
            headers={"Authorization": authorization} if authorization else {},
        )
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert (await client.get("/status")).status_code == 401


async def test_safe_bounded_http_errors_and_check():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=m.create_app(settings())),
        base_url="http://host",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as client:
        assert (await client.post("/cookies", content=b"x" * 4097)).status_code == 413
        response = await client.post("/cookies", json={"site": "private-value"})
        assert response.status_code == 422 and "private-value" not in response.text
        assert response.headers["cache-control"] == "no-store"
        response = await client.post("/cookies", json=request().model_dump(mode="json"))
        assert response.status_code == 503 and response.json() == {
            "cause": "extension_disconnected"
        }
        assert (await client.get("/status")).json() == {
            "connected": False,
            "version": None,
        }


@pytest.mark.parametrize(
    "origin", [None, "null", "http://127.0.0.1:19101", "chrome-extension://wrong"]
)
def test_origin_refusal(origin):
    with TestClient(m.create_app(settings())) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/extension", headers={"Origin": origin} if origin else {}
            ):
                pass


def test_auth_failure_and_timeout(monkeypatch):
    monkeypatch.setattr(m, "AUTH_TIMEOUT", 0.05)
    with TestClient(m.create_app(settings())) as client:
        with client.websocket_connect(
            "/extension", headers={"Origin": extension_origin()}
        ) as ws:
            with pytest.raises(WebSocketDisconnect):
                authenticate(ws, KEY + "wrong")
        with client.websocket_connect(
            "/extension", headers={"Origin": extension_origin()}
        ) as ws:
            ws.receive_json()
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


def test_single_profile_request_id_and_status():
    with TestClient(m.create_app(settings())) as client:
        with client.websocket_connect(
            "/extension", headers={"Origin": extension_origin()}
        ) as ws:
            assert authenticate(ws) == {"type": "ready"}
            assert client.get(
                "/status", headers={"Authorization": f"Bearer {TOKEN}"}
            ).json() == {"connected": True, "version": "1.0.0"}
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(
                    "/extension", headers={"Origin": extension_origin()}
                ):
                    pass
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
            with ThreadPoolExecutor() as pool:
                response = pool.submit(
                    client.post,
                    "/cookies",
                    json=request().model_dump(mode="json"),
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )
                message = ws.receive_json()
                assert message["domains"] == ["instagram.com"]
                ws.send_json(dict(type="cookies", request_id="0" * 32, cookies=[]))
                assert not response.done()
                ws.send_json(
                    dict(
                        type="cookies",
                        request_id=message["request_id"],
                        cookies=[COOKIE],
                    )
                )
                result = response.result(timeout=2)
                assert result.status_code == 200
                assert b"synthetic" in base64.b64decode(result.json()["cookies"])
        assert client.get(
            "/status", headers={"Authorization": f"Bearer {TOKEN}"}
        ).json() == {"connected": False, "version": None}


def test_connection_count_and_message_size_bounded():
    with TestClient(m.create_app(settings())) as client:
        with client.websocket_connect(
            "/extension", headers={"Origin": extension_origin()}
        ) as first:
            first.receive_json()
            with client.websocket_connect(
                "/extension", headers={"Origin": extension_origin()}
            ) as second:
                second.receive_json()
                with pytest.raises(WebSocketDisconnect):
                    with client.websocket_connect(
                        "/extension", headers={"Origin": extension_origin()}
                    ):
                        pass
                second.send_text("x" * (m.MAX_COOKIE_BYTES + 1))
                with pytest.raises(WebSocketDisconnect):
                    second.receive_json()


def test_pairing_key_independent():
    with pytest.raises(ValueError, match="must_differ"):
        m.create_app(
            CookieSourceSettings(
                cookie_source_token=SecretStr(TOKEN),
                cookie_source_pairing_key=SecretStr(TOKEN),
            )
        )


async def test_lifespan_closes_connection():
    app = m.create_app(settings())
    socket = AsyncMock()
    async with app.router.lifespan_context(app):
        app.state.cookie_source.connection = socket
    socket.close.assert_awaited_once_with(code=1001)
    assert app.state.cookie_source.connection is None


def test_simultaneous_authenticated_handshakes_keep_first_profile():
    with TestClient(m.create_app(settings())) as client:
        with client.websocket_connect(
            "/extension", headers={"Origin": extension_origin()}
        ) as first:
            first_challenge = first.receive_json()
            with client.websocket_connect(
                "/extension", headers={"Origin": extension_origin()}
            ) as second:
                second_challenge = second.receive_json()
                for ws in (first, second):
                    ws.send_json({"type": "challenge", "nonce": "a" * 64})
                    ws.receive_json()
                first.send_json(
                    {
                        "type": "proof",
                        "proof": m.proof(
                            KEY, "extension", first_challenge["nonce"], "a" * 64
                        ),
                        "version": "1.0.0",
                    }
                )
                assert first.receive_json() == {"type": "ready"}
                second.send_json(
                    {
                        "type": "proof",
                        "proof": m.proof(
                            KEY, "extension", second_challenge["nonce"], "a" * 64
                        ),
                        "version": "1.0.0",
                    }
                )
                with pytest.raises(WebSocketDisconnect):
                    second.receive_json()
                first.send_json({"type": "ping"})
                assert first.receive_json() == {"type": "pong"}


def test_server_application_heartbeat(monkeypatch):
    monkeypatch.setattr(m, "HEARTBEAT_SECONDS", 0.01)
    with TestClient(m.create_app(settings())) as client:
        with client.websocket_connect(
            "/extension", headers={"Origin": extension_origin()}
        ) as ws:
            authenticate(ws)
            assert ws.receive_json() == {"type": "ping"}
            ws.send_json({"type": "pong"})


# Independent minimal and incomplete account material per platform (no live values).
@pytest.mark.parametrize(
    "site,domain,names",
    [
        ("youtube", "youtube.com", ["LOGIN_INFO", "SAPISID"]),
        ("youtube", "youtube.com", ["LOGIN_INFO", "__Secure-3PAPISID"]),
        ("youtube", "youtube.com", ["LOGIN_INFO", "__Secure-1PAPISID"]),
        ("bilibili", "bilibili.com", ["SESSDATA"]),
        ("douyin", "douyin.com", ["sessionid"]),
        ("douyin", "douyin.com", ["sessionid_ss"]),
        ("xiaohongshu", "xiaohongshu.com", ["web_session"]),
        ("kuaishou", "kuaishou.com", ["passToken"]),
        (
            "kuaishou",
            "kuaishou.com",
            ["kuaishou.server.web_st", "kuaishou.server.web_ph"],
        ),
        ("weibo", "weibo.com", ["SUB"]),
        ("x", "x.com", ["auth_token", "ct0"]),
        ("x", "twitter.com", ["auth_token", "ct0"]),
        ("facebook", "facebook.com", ["c_user", "xs"]),
        ("instagram", "instagram.com", ["sessionid"]),
        ("qqvideo", "v.qq.com", ["v_vuserid", "v_vusession"]),
        ("youku", "youku.com", ["P_sck"]),
    ],
)
async def test_platform_required_cookies_and_stable_digest(source, site, domain, names):
    service, state = source
    state["cookies"] = [
        {**COOKIE, "domain": "." + domain, "name": name} for name in names
    ]
    first = await service.cookies(request(site))
    state["cookies"].append(
        {**COOKIE, "domain": "." + domain, "name": "visitor", "value": "rotating"}
    )
    assert (await service.cookies(request(site)))["digest"] == first["digest"]
    state["cookies"][0]["value"] = "different-account"
    assert (await service.cookies(request(site)))["digest"] != first["digest"]
    state["cookies"] = state["cookies"][1:]
    with pytest.raises(m.IdentityUnavailable, match="credential_missing"):
        await service.cookies(request(site))


@pytest.mark.parametrize(
    "names",
    [
        ["SAPISID"],
        ["LOGIN_INFO"],
        ["LOGIN_INFO", "__Secure-3PSID"],
        ["VISITOR_INFO1_LIVE"],
    ],
)
async def test_youtube_stale_sid_and_visitor_material_are_not_login(source, names):
    service, state = source
    state["cookies"] = [
        {**COOKIE, "domain": ".youtube.com", "name": name} for name in names
    ]
    with pytest.raises(m.IdentityUnavailable, match="credential_missing"):
        await service.cookies(request("youtube"))
