from contextlib import asynccontextmanager

import httpx
import pytest
from app.core.config import Settings
from app.workers.session.broker_app import create_app, settings_factory
from app.workers.session.rpc import SignedClient


async def test_bridge_readiness_tracks_resources_not_login_state():
    closed = []

    @asynccontextmanager
    async def factory():
        async with httpx.AsyncClient(base_url="http://offline") as source:
            try:
                yield SignedClient(source, b"s" * 32)
            finally:
                closed.append(True)

    app = create_app(source_factory=factory, rpc_secret=b"r" * 32)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://bridge"
    ) as client:
        assert (await client.get("/health/ready")).status_code == 503
        async with app.router.lifespan_context(app):
            assert (await client.get("/health/ready")).status_code == 200
        assert (await client.get("/health/ready")).status_code == 503
    assert closed == [True]


def test_bridge_requires_source_secret():
    with pytest.raises(SystemExit, match="SITE_SESSION_AGENT_SECRET"):
        settings_factory(Settings(app_env="test", site_session_agent_secret=None))


async def test_bridge_manual_login_does_not_contact_source():
    @asynccontextmanager
    async def factory():
        pytest.fail("removed login must not contact the source")
        yield

    app = create_app(source_factory=factory, rpc_secret=b"r" * 32)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://bridge"
    ) as client:
        response = await client.post("/internal/site-sessions/login", json={})
    assert response.status_code == 404
