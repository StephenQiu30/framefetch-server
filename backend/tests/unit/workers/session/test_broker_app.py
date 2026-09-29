import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
from app.workers.session.broker import LeaseGrant, SessionNotReady
from app.workers.session.broker_app import create_app, settings_factory
from app.workers.session.contracts import (
    FAILURE_PATH,
    LEASE_PATH,
    FailureReport,
    LeaseRequest,
    LeaseResponse,
)
from app.workers.session.rpc import RpcError, SignedClient
from app.workers.session.sealing import decode, encode, public_key
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

SECRET = b"r" * 32
KEY = encode(public_key(X25519PrivateKey.generate()))


class StubBroker:
    def __init__(self) -> None:
        self.scans = 0
        self.failures: list[dict] = []

    warming = False

    async def scan(self) -> None:
        self.scans += 1

    async def warming_up(self) -> bool:
        return self.warming

    async def lease(self, *, task_id, site, seed_revision, runner_key):
        if site == "busy.com":
            raise SessionNotReady(site)
        return LeaseGrant(
            site,
            seed_revision,
            3,
            1_900_000_000,
            b"sealed",
            None,
            public_key(X25519PrivateKey.generate()),
        )

    async def report_failure(self, **kwargs) -> None:
        self.failures.append(kwargs)


@asynccontextmanager
async def running(broker: StubBroker):
    @asynccontextmanager
    async def factory():
        yield broker

    app = create_app(broker_factory=factory, rpc_secret=SECRET, scan_seconds=0.01)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://b") as raw:
            yield raw


async def test_lease_failure_and_health_endpoints():
    broker = StubBroker()
    async with running(broker) as raw:
        signed = SignedClient(raw, SECRET)
        grant = await signed.post(
            LEASE_PATH,
            LeaseRequest(
                task_id="t1", site="youtube.com", seed_revision=2, public_key=KEY
            ),
            LeaseResponse,
        )
        assert decode(grant.jar) == b"sealed" and grant.jar_version == 3
        with pytest.raises(RpcError) as error:
            await signed.post(
                LEASE_PATH,
                LeaseRequest(
                    task_id="t1", site="busy.com", seed_revision=1, public_key=KEY
                ),
                LeaseResponse,
            )
        assert (error.value.code, error.value.status) == (
            "provider_session_not_ready",
            409,
        )
        with pytest.raises(RpcError) as error:
            await signed.post(
                LEASE_PATH,
                LeaseRequest(
                    task_id="t1", site="youtube.com", seed_revision=1, public_key="AAAA"
                ),
                LeaseResponse,
            )
        assert error.value.status == 422

        await signed.post_empty(
            FAILURE_PATH,
            FailureReport(
                site="youtube.com", seed_revision=2, error_code="egress_challenged"
            ),
        )
        assert broker.failures == [
            {
                "site": "youtube.com",
                "seed_revision": 2,
                "error_code": "egress_challenged",
            }
        ]
        unsigned = await raw.post(LEASE_PATH, json={})
        assert unsigned.status_code == 401

        await asyncio.sleep(0.05)
        assert broker.scans >= 2
        assert (await raw.get("/health/ready")).status_code == 200
        assert (await raw.get("/docs")).status_code == 404


async def test_ready_requires_a_recent_scan():
    class Failing(StubBroker):
        async def scan(self) -> None:
            raise RuntimeError("database down")

    async with running(Failing()) as raw:
        await asyncio.sleep(0.03)
        assert (await raw.get("/health/ready")).status_code == 503
        assert (await raw.get("/health/live")).status_code == 200


def test_broker_refuses_to_start_without_its_secrets():
    from app.core.config import Settings

    with pytest.raises(SystemExit):
        settings_factory(Settings(_env_file=None, service_role="session-broker"))


async def _ready_status(broker: StubBroker, warmup_seconds: float) -> list[int]:
    @asynccontextmanager
    async def factory():
        yield broker

    app = create_app(
        broker_factory=factory,
        rpc_secret=SECRET,
        scan_seconds=0.01,
        warmup_seconds=warmup_seconds,
    )
    codes = []
    async with app.router.lifespan_context(app):
        await asyncio.sleep(0.05)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://b") as raw:
            codes.append((await raw.get("/health/ready")).status_code)
            broker.warming = False
            codes.append((await raw.get("/health/ready")).status_code)
            broker.warming = (
                True  # latched: a later maintenance pass is not a cold start
            )
            codes.append((await raw.get("/health/ready")).status_code)
    return codes


async def test_ready_waits_for_live_verification_then_latches():
    broker = StubBroker()
    broker.warming = True
    assert await _ready_status(broker, warmup_seconds=60) == [503, 200, 200]


async def test_warmup_is_bounded_so_a_stuck_session_cannot_block_startup():
    broker = StubBroker()
    broker.warming = True
    assert await _ready_status(broker, warmup_seconds=0) == [200, 200, 200]
