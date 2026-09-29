from contextlib import asynccontextmanager

import httpx
import pytest
from app.workers.session.broker_app import create_app, settings_factory
from app.workers.session.chrome_broker import (
    LeaseGrant,
    SessionLoginRequired,
    SessionNotReady,
)
from app.workers.session.contracts import (
    LEASE_PATH,
    STATUS_PATH,
    LeaseRequest,
    LeaseResponse,
    StatusRequest,
    StatusResponse,
)
from app.workers.session.rpc import RpcError, SignedClient
from app.workers.session.sealing import decode, encode, public_key
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

SECRET = b"r" * 32
KEY = encode(public_key(X25519PrivateKey.generate()))


class StubBroker:
    async def ready_revision(self, site):
        if site == "busy.com":
            raise SessionNotReady(site)
        if site == "loggedout.com":
            raise SessionLoginRequired(site)
        return 2

    async def lease(self, *, task_id, site, seed_revision, runner_key):
        await self.ready_revision(site)
        return LeaseGrant(site, seed_revision, 1_900_000_000, b"sealed", None)


@asynccontextmanager
async def running(broker: StubBroker):
    @asynccontextmanager
    async def factory():
        yield broker

    app = create_app(broker_factory=factory, rpc_secret=SECRET)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://b") as raw:
            yield raw


async def test_lease_and_health_endpoints():
    async with running(StubBroker()) as raw:
        signed = SignedClient(raw, SECRET)
        grant = await signed.post(
            LEASE_PATH,
            LeaseRequest(
                task_id="t1", site="youtube.com", seed_revision=2, public_key=KEY
            ),
            LeaseResponse,
        )
        assert decode(grant.jar) == b"sealed"
        assert set(grant.model_dump()) == {
            "site",
            "seed_revision",
            "expires_at",
            "jar",
            "headers",
        }
        with pytest.raises(RpcError) as error:
            await signed.post(
                LEASE_PATH,
                LeaseRequest(
                    task_id="t1", site="youtube.com", seed_revision=1, public_key="AAAA"
                ),
                LeaseResponse,
            )
        assert error.value.status == 422
        assert (await raw.post(LEASE_PATH, json={})).status_code == 401
        assert (await raw.get("/health/ready")).status_code == 200
        assert (await raw.get("/health/live")).status_code == 200
        assert (await raw.get("/docs")).status_code == 404


@pytest.mark.parametrize(
    ("site", "code"),
    [
        ("busy.com", "provider_session_not_ready"),
        ("loggedout.com", "credential_required"),
    ],
)
async def test_source_failure_does_not_block_relay_startup(site, code):
    async with running(StubBroker()) as raw:
        signed = SignedClient(raw, SECRET)
        assert (await raw.get("/health/ready")).status_code == 200
        for path, body, response in (
            (STATUS_PATH, StatusRequest(site=site), StatusResponse),
            (
                LEASE_PATH,
                LeaseRequest(task_id="t1", site=site, seed_revision=1, public_key=KEY),
                LeaseResponse,
            ),
        ):
            with pytest.raises(RpcError) as caught:
                await signed.post(path, body, response)
            assert (caught.value.status, caught.value.code) == (409, code)
        assert (await raw.get("/health/ready")).status_code == 200


async def test_ready_tracks_resource_startup_and_shutdown():
    closed = []

    @asynccontextmanager
    async def factory():
        try:
            yield StubBroker()
        finally:
            closed.append(True)

    app = create_app(broker_factory=factory, rpc_secret=SECRET)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://b"
    ) as raw:
        assert (await raw.get("/health/ready")).status_code == 503
        async with app.router.lifespan_context(app):
            assert (await raw.get("/health/ready")).status_code == 200
        assert (await raw.get("/health/ready")).status_code == 503
    assert closed == [True]


@pytest.mark.parametrize("route", ["rotation", "failures"])
async def test_unused_session_writeback_routes_are_not_exposed(route):
    async with running(StubBroker()) as raw:
        response = await raw.post(f"/internal/site-sessions/{route}", json={})
        assert response.status_code == 404


def test_broker_refuses_to_start_without_its_secrets():
    from app.core.config import Settings

    with pytest.raises(SystemExit):
        settings_factory(Settings(_env_file=None, service_role="session-broker"))
