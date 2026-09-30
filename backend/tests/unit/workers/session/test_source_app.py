from contextlib import asynccontextmanager
from dataclasses import replace

import httpx
import pytest
from app.workers.session.broker_app import create_app as bridge_app
from app.workers.session.chrome_source import SourceSnapshot, SourceUnavailable
from app.workers.session.contracts import (
    LEASE_PATH,
    STATUS_PATH,
    LeaseRequest,
    LeaseResponse,
    StatusRequest,
    StatusResponse,
    lease_associated_data,
)
from app.workers.session.rpc import RpcError, SignedClient
from app.workers.session.sealing import (
    SealError,
    decode,
    encode,
    open_sealed,
    public_key,
)
from app.workers.session.source_app import create_app
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

SOURCE_SECRET = b"s" * 32
RUNNER_SECRET = b"r" * 32
COOKIE = (
    b"# Netscape HTTP Cookie File\n"
    b".youtube.com\tTRUE\t/\tTRUE\t4102444800\tSID\tsynthetic\n"
)


class Source:
    def __init__(self):
        self.snapshot = SourceSnapshot("youtube.com", 7, COOKIE, b"headers")
        self.calls = []
        self.error = None
        self.started = False
        self.closed = False
        self.start_error = None

    async def start(self):
        self.started = True
        if self.start_error:
            raise self.start_error

    async def close(self):
        self.started = False
        self.closed = True

    async def read(self, site, *, include_headers=False):
        self.calls.append((site, include_headers))
        if self.error:
            raise SourceUnavailable(self.error)
        return self.snapshot


@asynccontextmanager
async def clients(source):
    app = create_app(source=source, secret=SOURCE_SECRET)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://source"
        ) as raw,
    ):

        @asynccontextmanager
        async def factory():
            yield SignedClient(raw, SOURCE_SECRET)

        bridge = bridge_app(source_factory=factory, rpc_secret=RUNNER_SECRET)
        async with (
            bridge.router.lifespan_context(bridge),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=bridge), base_url="http://bridge"
            ) as relayed,
        ):
            yield raw, SignedClient(relayed, RUNNER_SECRET)


async def test_end_to_end_sealed_lease_and_source_generation():
    source = Source()
    key = X25519PrivateKey.generate()
    async with clients(source) as (raw, client):
        status = await client.post(
            STATUS_PATH, StatusRequest(site="youtube.com"), StatusResponse
        )
        assert status.source_generation == 7
        request = LeaseRequest(
            task_id="task",
            site="youtube.com",
            source_generation=7,
            public_key=encode(public_key(key)),
        )
        grant = await client.post(LEASE_PATH, request, LeaseResponse)
        aad = lease_associated_data("jar", "task", "youtube.com", 7, grant.expires_at)
        assert open_sealed(decode(grant.jar), key, associated_data=aad) == COOKIE
        assert (
            open_sealed(
                decode(grant.headers),
                key,
                associated_data=lease_associated_data(
                    "headers", "task", "youtube.com", 7, grant.expires_at
                ),
            )
            == b"headers"
        )
        assert "synthetic" not in grant.model_dump_json()
        with pytest.raises(SealError):
            open_sealed(
                decode(grant.jar),
                key,
                associated_data=lease_associated_data(
                    "jar", "another", "youtube.com", 7, grant.expires_at
                ),
            )
        source.snapshot = replace(source.snapshot, generation=8)
        with pytest.raises(RpcError, match="credential_revoked"):
            await client.post(LEASE_PATH, request, LeaseResponse)
        assert (
            await raw.post(LEASE_PATH, json=request.model_dump())
        ).status_code == 401
        wrong = SignedClient(raw, RUNNER_SECRET)
        with pytest.raises(RpcError, match="invalid_signature"):
            await wrong.post(
                STATUS_PATH, StatusRequest(site="youtube.com"), StatusResponse
            )
    assert not source.started


@pytest.mark.parametrize("code", ["credential_required", "provider_session_not_ready"])
async def test_unavailable_source_preserves_reason_across_bridge(code):
    source = Source()
    source.error = code
    async with clients(source) as (_, client):
        with pytest.raises(RpcError, match=code):
            await client.post(
                STATUS_PATH, StatusRequest(site="youtube.com"), StatusResponse
            )


@pytest.mark.parametrize(
    "path",
    [
        "/internal/browser/connect",
        "/internal/browser/disconnect",
        "/internal/browser/poll",
        "/internal/browser/reply",
        "/internal/site-sessions/login",
    ],
)
async def test_manual_browser_routes_are_removed_without_reading_source(path):
    source = Source()
    async with clients(source) as (raw, _):
        assert (await raw.post(path, json={})).status_code == 404
    assert source.calls == []


async def test_health_is_lifecycle_readiness_and_does_not_probe_accounts():
    source = Source()
    app = create_app(source=source, secret=SOURCE_SECRET)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://source"
    ) as raw:
        assert (await raw.get("/health")).status_code == 503
        async with app.router.lifespan_context(app):
            assert (await raw.get("/health")).status_code == 200
            assert source.calls == []
        assert (await raw.get("/health")).status_code == 503
    assert source.closed


async def test_startup_failure_closes_partial_source_resources():
    source = Source()
    source.start_error = RuntimeError("synthetic startup failure")
    app = create_app(source=source, secret=SOURCE_SECRET)
    with pytest.raises(RuntimeError, match="synthetic startup failure"):
        async with app.router.lifespan_context(app):
            pytest.fail("failed source must not start serving")
    assert source.closed and not source.started


async def test_invalid_recipient_is_rejected_before_reading_material():
    source = Source()
    async with clients(source) as (raw, _):
        direct = SignedClient(raw, SOURCE_SECRET)
        with pytest.raises(RpcError, match="invalid_request"):
            await direct.post(
                LEASE_PATH,
                LeaseRequest(
                    task_id="task",
                    site="youtube.com",
                    source_generation=7,
                    public_key="invalid-key",
                ),
                LeaseResponse,
            )
    assert source.calls == []
