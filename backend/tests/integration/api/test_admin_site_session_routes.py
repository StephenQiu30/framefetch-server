from __future__ import annotations

import base64
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from app.api.deps import get_current_admin, get_current_user
from app.core.config import Settings
from app.integrations.site_session_admin import SiteSessionAdmin
from app.main import create_app
from app.services.auth.models import CurrentUser, UserRole
from app.services.site_sessions import SiteSessionState, SiteSessionStatus
from app.workers.session.broker import LoginNotAccepted
from app.workers.session.broker_app import create_app as create_broker
from app.workers.session.browser_client import LoginRejected
from app.workers.session.contracts import LoginFrame, LoginStarted
from app.workers.session.sealing import encode

NOW = datetime(2026, 9, 28, tzinfo=UTC)
ADMIN = CurrentUser(
    UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    "admin",
    "admin@example.com",
    UserRole.ADMIN,
    NOW,
    NOW,
)
USER = CurrentUser(
    UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
    "user",
    "user@example.com",
    UserRole.USER,
    NOW,
    NOW,
)
ADMIN_SECRET = b"a" * 32


def status(site: str, state: SiteSessionState, revision: int = 2) -> SiteSessionStatus:
    return SiteSessionStatus(
        site=site,
        provider_key=None,
        state=state,
        seed_revision=revision,
        jar_version=0,
        egress_route="default",
        seeded_at=NOW,
        refreshed_at=None,
        verified_at=NOW,
        last_error_code=None,
        consecutive_failures=0,
        state_changed_at=NOW,
    )


class States:
    def __init__(self) -> None:
        self.rows = {
            "youtube.com": status("youtube.com", SiteSessionState.READY),
            "example.com": status(
                "example.com", SiteSessionState.RESEED_REQUIRED, revision=1
            ),
        }

    async def list(self):
        return tuple(self.rows.values())

    async def get(self, site):
        return self.rows.get(site)


class Secrets:
    def __init__(self) -> None:
        self.revoked: list[tuple[str, int]] = []

    async def revoke(self, site, *, expected_seed_revision):
        self.revoked.append((site, expected_seed_revision))


class Broker:
    def __init__(self) -> None:
        self.started: list[tuple[str, str | None]] = []
        self.actions: list = []

    async def scan(self):
        pass

    async def login_start(self, site, url):
        if site == "reddit.com":
            raise LoginRejected("login_busy", 409)
        self.started.append((site, url))
        return LoginStarted(login_id="login_1", site=site)

    async def login_frame(self, login_id):
        if login_id != "login_1":
            raise LoginRejected("login_not_found", 404)
        return LoginFrame(
            image=encode(b"\xff\xd8jpeg"), host="yuanbao.tencent.com", logged_in=True
        )

    async def login_input(self, login_id, actions):
        self.actions += actions

    async def login_finish(self, login_id):
        if login_id == "bare":
            raise LoginNotAccepted("weixin.qq.com")
        return "weixin.qq.com", 3

    async def login_cancel(self, login_id):
        pass


@asynccontextmanager
async def api(user: CurrentUser = ADMIN):
    broker = Broker()

    @asynccontextmanager
    async def factory():
        yield broker

    broker_app = create_broker(
        broker_factory=factory,
        rpc_secret=b"r" * 32,
        admin_secret=ADMIN_SECRET,
        scan_seconds=60,
    )
    states, secrets = States(), Secrets()
    async with broker_app.router.lifespan_context(broker_app):
        admin = SiteSessionAdmin(
            states=states,  # type: ignore[arg-type]
            secrets=secrets,  # type: ignore[arg-type]
            broker_url="http://broker",
            admin_secret=ADMIN_SECRET,
            client=httpx.AsyncClient(
                transport=httpx.ASGITransport(app=broker_app), base_url="http://broker"
            ),
        )
        app = create_app(Settings(app_env="test"))
        app.state.services.site_session_admin = admin
        dependency = get_current_admin if user is ADMIN else get_current_user
        app.dependency_overrides[dependency] = lambda: user
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://api"
        ) as client:
            yield client, broker, secrets
        await admin.close()


async def test_list_shows_every_known_platform_and_every_stored_site():
    async with api() as (client, _, _):
        response = await client.get("/api/admin/site-sessions")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    items = {item["site"]: item for item in response.json()["data"]["items"]}
    assert items["youtube.com"]["state"] == "ready"
    assert items["youtube.com"]["proves_login"] is True
    assert items["weixin.qq.com"]["state"] is None
    assert items["weixin.qq.com"]["provider_key"] == "wechat_channels"
    assert items["example.com"]["state"] == "reseed_required"
    assert items["example.com"]["proves_login"] is False


async def test_remote_login_round_trip():
    async with api() as (client, broker, _):
        started = await client.post(
            "/api/admin/site-sessions/logins", json={"target": "weixin.qq.com"}
        )
        frame = await client.get("/api/admin/site-sessions/logins/login_1/frame")
        sent = await client.post(
            "/api/admin/site-sessions/logins/login_1/input",
            json={"actions": [{"kind": "drag", "x": 1, "y": 2, "x2": 300, "y2": 2}]},
        )
        finished = await client.post("/api/admin/site-sessions/logins/login_1/finish")
        cancelled = await client.delete("/api/admin/site-sessions/logins/login_1")
        by_url = await client.post(
            "/api/admin/site-sessions/logins",
            json={"target": "https://media.example.com/watch/1"},
        )

    assert started.status_code == 201
    assert started.json()["data"] == {
        "login_id": "login_1",
        "site": "weixin.qq.com",
        "width": 1280,
        "height": 800,
    }
    data = frame.json()["data"]
    assert base64.b64decode(data["image"]) == b"\xff\xd8jpeg"
    assert (data["host"], data["logged_in"]) == ("yuanbao.tencent.com", True)
    assert sent.status_code == 204
    assert broker.actions[0].kind == "drag" and broker.actions[0].x2 == 300
    assert finished.json()["data"] == {"site": "weixin.qq.com", "seed_revision": 3}
    assert cancelled.status_code == 204
    assert by_url.status_code == 201
    assert broker.started[-1] == ("example.com", "https://media.example.com/watch/1")


@pytest.mark.parametrize(
    ("method", "path", "body", "expected"),
    [
        ("post", "/logins", {"target": "10.0.0.1"}, (422, "site_session_invalid")),
        ("post", "/logins", {"target": "reddit.com"}, (409, "site_session_login_busy")),
        ("get", "/logins/gone/frame", None, (404, "site_session_login_not_found")),
        ("post", "/logins/bare/finish", None, (409, "site_session_login_rejected")),
        (
            "post",
            "/logins/login_1/input",
            {"actions": [{"kind": "click", "x": 1}]},
            (422, "invalid_request"),
        ),
        ("delete", "/weixin.qq.com", None, (404, "site_session_not_found")),
    ],
)
async def test_errors_are_stable_codes(method, path, body, expected):
    async with api() as (client, _, _):
        kwargs = {} if body is None else {"json": body}
        response = await getattr(client, method)(
            f"/api/admin/site-sessions{path}", **kwargs
        )
    assert (response.status_code, response.json()["code"]) == expected


async def test_revoke_uses_the_current_revision():
    async with api() as (client, _, secrets):
        response = await client.delete("/api/admin/site-sessions/youtube.com")
    assert response.status_code == 204
    assert secrets.revoked == [("youtube.com", 2)]


async def test_non_admins_cannot_see_or_drive_logins():
    async with api(USER) as (client, broker, _):
        listed = await client.get("/api/admin/site-sessions")
        started = await client.post(
            "/api/admin/site-sessions/logins", json={"target": "weixin.qq.com"}
        )
    assert (listed.status_code, started.status_code) == (403, 403)
    assert broker.started == []
