from contextlib import asynccontextmanager

import httpx
import pytest
from app.workers.session.browser import HeadersUnavailable, VisitResult
from app.workers.session.browser_app import create_app
from app.workers.session.browser_client import BrowserUnavailable, HttpSessionBrowser
from app.workers.session.contracts import BrowserOutcome as O
from app.workers.session.contracts import lease_associated_data
from app.workers.session.rpc import SignedClient
from app.workers.session.sealing import open_sealed, public_key
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

SECRET = b"b" * 32


class FakeSiteBrowser:
    def __init__(self) -> None:
        self.received: list[bytes] = []
        self.forgotten: list[str] = []

    async def bootstrap(self, site, jar):
        self.received.append(jar)
        return VisitResult(O.VERIFIED, jar=jar + b"-rotated")

    async def keepalive(self, site):
        if site == "reddit.com":
            return VisitResult(O.PROFILE_MISSING)
        return VisitResult(O.LOGGED_OUT, "session_logged_out")

    async def headers(self, site):
        if site != "weixin.qq.com":
            raise HeadersUnavailable(site)
        return b'{"hy_user":"u"}'

    async def forget(self, site):
        self.forgotten.append(site)


@asynccontextmanager
async def client(fake: FakeSiteBrowser, secret: bytes = SECRET):
    @asynccontextmanager
    async def factory():
        yield fake

    app = create_app(browser_factory=factory, secret=SECRET)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://b") as raw:
            yield HttpSessionBrowser(SignedClient(raw, secret)), raw


async def test_broker_client_and_browser_server_agree_on_sealed_contracts():
    fake = FakeSiteBrowser()
    async with client(fake) as (browser, raw):
        report = await browser.bootstrap("youtube.com", 3, b"jar")
        assert fake.received == [b"jar"]
        assert (report.outcome, report.jar) == (O.VERIFIED, b"jar-rotated")

        report = await browser.keepalive("youtube.com", 3)
        assert (report.outcome, report.error_code, report.jar) == (
            O.LOGGED_OUT,
            "session_logged_out",
            None,
        )
        assert (await browser.keepalive("reddit.com", 1)).outcome is O.PROFILE_MISSING

        runner = X25519PrivateKey.generate()
        sealed = await browser.headers(
            "weixin.qq.com",
            2,
            task_id="t",
            expires_at=99,
            runner_key=public_key(runner),
        )
        aad = lease_associated_data("headers", "t", "weixin.qq.com", 2, 99)
        assert open_sealed(sealed, runner, associated_data=aad) == b'{"hy_user":"u"}'
        with pytest.raises(BrowserUnavailable):
            await browser.headers(
                "youtube.com",
                2,
                task_id="t",
                expires_at=99,
                runner_key=public_key(runner),
            )

        await browser.forget("youtube.com")
        assert fake.forgotten == ["youtube.com"]
        assert (await raw.get("/health/live")).status_code == 200
        assert (await raw.post("/v1/identity", json={})).status_code == 401


async def test_a_wrong_secret_is_refused():
    async with client(FakeSiteBrowser(), secret=b"x" * 32) as (browser, _):
        with pytest.raises(BrowserUnavailable):
            await browser.keepalive("youtube.com", 1)


async def test_slow_or_broken_browser_operations_are_unavailable(monkeypatch):
    from app.workers.session import browser_app

    class Broken(FakeSiteBrowser):
        async def keepalive(self, site):
            raise OSError("disk full")

    async with client(Broken()) as (browser, _):
        assert (await browser.keepalive("youtube.com", 1)).outcome is O.UNAVAILABLE
    assert browser_app.OPERATION_TIMEOUT_SECONDS == 60
