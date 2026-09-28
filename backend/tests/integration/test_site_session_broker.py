from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from app.core.security.site_session_cipher import SiteSessionCipher
from app.repositories.providers.site_sessions import (
    SiteSessionSecret,
    SiteSessionSecrets,
    SiteSessionStates,
)
from app.services.site_sessions import SiteSessionState as S
from app.workers.session.broker import SessionBroker, SessionNotReady
from app.workers.session.browser_client import BrowserReport, BrowserUnavailable
from app.workers.session.contracts import BrowserOutcome as O
from app.workers.session.contracts import lease_associated_data
from app.workers.session.sealing import SealError, open_sealed, public_key
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

SITE = "youtube.com"


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now


class FakeBrowser:
    def __init__(self) -> None:
        self.bootstrap_reports: list[BrowserReport | Exception] = []
        self.keepalive_reports: list[BrowserReport | Exception] = []
        self.bootstrapped: list[tuple[str, int, bytes]] = []
        self.keepalives: list[tuple[str, int]] = []
        self.forgotten: list[str] = []
        self.header_calls: list[dict] = []

    async def bootstrap(self, site, seed_revision, jar):
        self.bootstrapped.append((site, seed_revision, jar))
        return _next(self.bootstrap_reports)

    async def keepalive(self, site, seed_revision):
        self.keepalives.append((site, seed_revision))
        return _next(self.keepalive_reports)

    async def headers(self, site, seed_revision, **kwargs):
        self.header_calls.append({"site": site, **kwargs})
        return b"sealed-headers"

    async def forget(self, site):
        self.forgotten.append(site)


def _next(queue):
    item = queue.pop(0)
    if isinstance(item, Exception):
        raise item
    return item


@pytest.fixture
def world(postgres_engine):
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    cipher = SiteSessionCipher(Fernet.generate_key().decode())
    clock = Clock()
    browser = FakeBrowser()
    states, secrets = SiteSessionStates(sessions), SiteSessionSecrets(sessions)
    broker = SessionBroker(
        states=states,
        secrets=secrets,
        cipher=cipher,
        browser=browser,
        clock=clock,
        jitter=lambda low, high: 0,
    )

    async def seed(site=SITE, jar=b"seed-jar", expected=0):
        return await secrets.seed(
            site,
            provider_key=None,
            expected_seed_revision=expected,
            ciphertext=cipher.encrypt(site, expected + 1, 0, jar),
            egress_route="default",
        )

    class World:
        pass

    w = World()
    w.__dict__.update(
        broker=broker,
        browser=browser,
        states=states,
        secrets=secrets,
        cipher=cipher,
        clock=clock,
        seed=seed,
        engine=postgres_engine,
    )
    return w


async def stored_jar(w, site=SITE) -> bytes:
    secret = await w.secrets.read(site)
    s = secret.status
    return w.cipher.decrypt(site, s.seed_revision, s.jar_version, secret.ciphertext)


async def test_import_is_bootstrapped_verified_and_rotation_stored(world):
    w = world
    await w.seed()
    w.browser.bootstrap_reports.append(BrowserReport(O.VERIFIED, jar=b"rotated"))
    await w.broker.scan()

    assert w.browser.bootstrapped == [(SITE, 1, b"seed-jar")]
    status = await w.states.get(SITE)
    assert status.state is S.READY and status.verified_at is not None
    assert status.jar_version == 1 and await stored_jar(w) == b"rotated"
    # Not due yet: no second browser call.
    await w.broker.scan()
    assert w.browser.keepalives == []


async def test_unreachable_browser_leaves_the_import_for_the_next_scan(world):
    w = world
    await w.seed()
    w.browser.bootstrap_reports += [
        BrowserUnavailable("down"),
        BrowserReport(O.UNAVAILABLE),
        BrowserReport(O.VERIFIED, jar=b"seed-jar"),
    ]
    await w.broker.scan()
    assert (await w.states.get(SITE)).state is S.VERIFYING
    await w.broker.scan()
    assert (await w.states.get(SITE)).state is S.VERIFYING
    await w.broker.scan()
    status = await w.states.get(SITE)
    # An unchanged jar is not rewritten.
    assert status.state is S.READY and status.jar_version == 0


async def test_logged_out_import_requires_reimport_with_one_alert(world, caplog):
    w = world
    await w.seed()
    w.browser.bootstrap_reports.append(BrowserReport(O.LOGGED_OUT))
    with caplog.at_level(logging.WARNING):
        await w.broker.scan()
        await w.broker.scan()
    status = await w.states.get(SITE)
    assert status.state is S.RESEED_REQUIRED
    assert status.last_error_code == "session_logged_out"
    assert len(w.browser.bootstrapped) == 1
    alerts = [r for r in caplog.records if "requires re-import" in r.getMessage()]
    assert len(alerts) == 1 and "session_logged_out" in alerts[0].getMessage()


async def test_keepalive_schedule_and_profile_rebuild(world):
    w = world
    await w.seed()
    w.browser.bootstrap_reports.append(BrowserReport(O.VERIFIED, jar=b"v1"))
    await w.broker.scan()

    w.clock.now += timedelta(seconds=1801)
    w.browser.keepalive_reports.append(BrowserReport(O.PROFILE_MISSING))
    w.browser.bootstrap_reports.append(BrowserReport(O.VERIFIED, jar=b"v2"))
    await w.broker.scan()
    assert w.browser.keepalives == [(SITE, 1)]
    assert w.browser.bootstrapped[-1] == (SITE, 1, b"v1")
    assert await stored_jar(w) == b"v2"
    assert (await w.states.get(SITE)).state is S.READY

    await w.broker.scan()
    assert len(w.browser.keepalives) == 1


async def test_auth_failures_degrade_reverify_and_escalate(world):
    w = world
    await w.seed()
    w.browser.bootstrap_reports.append(BrowserReport(O.VERIFIED))
    await w.broker.scan()

    await w.broker.report_failure(site=SITE, seed_revision=1, error_code="pot_rejected")
    assert (await w.states.get(SITE)).state is S.READY
    await w.broker.report_failure(
        site=SITE, seed_revision=9, error_code="egress_challenged"
    )
    assert (await w.states.get(SITE)).state is S.READY

    await w.broker.report_failure(
        site=SITE, seed_revision=1, error_code="egress_challenged"
    )
    assert (await w.states.get(SITE)).state is S.DEGRADED
    # Degraded sites are re-verified on the very next scan.
    w.browser.keepalive_reports.append(BrowserReport(O.VERIFIED))
    await w.broker.scan()
    status = await w.states.get(SITE)
    assert status.state is S.READY and status.consecutive_failures == 0

    for _ in range(2):
        await w.broker.report_failure(
            site=SITE, seed_revision=1, error_code="credential_expired"
        )
    w.browser.keepalive_reports.append(
        BrowserReport(O.AUTH_FAILURE, "egress_challenged")
    )
    await w.broker.scan()
    status = await w.states.get(SITE)
    assert status.state is S.RESEED_REQUIRED and status.consecutive_failures == 3


async def test_degraded_deadline_counts_from_entering_the_state(world):
    w = world
    await w.seed()
    w.browser.bootstrap_reports.append(BrowserReport(O.VERIFIED))
    await w.broker.scan()
    await w.broker.report_failure(
        site=SITE, seed_revision=1, error_code="credential_expired"
    )
    entered = (await w.states.get(SITE)).state_changed_at
    await w.broker.report_failure(
        site=SITE, seed_revision=1, error_code="credential_expired"
    )
    assert (await w.states.get(SITE)).state_changed_at == entered

    async with w.engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE site_sessions "
                "SET state_changed_at = now() - interval '25 hours'"
            )
        )
    w.clock.now = datetime.now(UTC)
    await w.broker.scan()
    status = await w.states.get(SITE)
    assert (
        status.state is S.RESEED_REQUIRED
        and status.last_error_code == "degraded_timeout"
    )


async def test_leases_are_sealed_to_the_runner_task(world):
    w = world
    await w.seed()
    runner = X25519PrivateKey.generate()
    with pytest.raises(SessionNotReady):
        await w.broker.lease(
            task_id="t1", site=SITE, seed_revision=1, runner_key=public_key(runner)
        )
    w.browser.bootstrap_reports.append(BrowserReport(O.VERIFIED, jar=b"live"))
    await w.broker.scan()

    grant = await w.broker.lease(
        task_id="t1", site=SITE, seed_revision=1, runner_key=public_key(runner)
    )
    assert grant.headers is None and grant.jar_version == 1
    assert grant.expires_at == int((w.clock.now + timedelta(seconds=600)).timestamp())
    aad = lease_associated_data("jar", "t1", SITE, 1, grant.expires_at)
    assert open_sealed(grant.jar, runner, associated_data=aad) == b"live"
    with pytest.raises(SealError):
        open_sealed(
            grant.jar,
            runner,
            associated_data=lease_associated_data(
                "jar", "t2", SITE, 1, grant.expires_at
            ),
        )
    with pytest.raises(SessionNotReady):
        await w.broker.lease(
            task_id="t1", site=SITE, seed_revision=2, runner_key=public_key(runner)
        )
    with pytest.raises(SessionNotReady):
        await w.broker.lease(
            task_id="t1",
            site="other.com",
            seed_revision=1,
            runner_key=public_key(runner),
        )


async def test_header_plugin_sites_relay_browser_sealed_headers(world):
    w = world
    await w.seed(site="weixin.qq.com")
    w.browser.bootstrap_reports.append(BrowserReport(O.VERIFIED))
    await w.broker.scan()
    runner = public_key(X25519PrivateKey.generate())
    grant = await w.broker.lease(
        task_id="t1", site="weixin.qq.com", seed_revision=1, runner_key=runner
    )
    assert grant.headers == b"sealed-headers"
    assert w.browser.header_calls == [
        {
            "site": "weixin.qq.com",
            "task_id": "t1",
            "expires_at": grant.expires_at,
            "runner_key": runner,
        }
    ]


async def test_reimport_invalidates_late_rotation_and_revocation_forgets_once(world):
    w = world
    await w.seed()
    w.browser.bootstrap_reports.append(BrowserReport(O.VERIFIED))
    await w.broker.scan()
    assert await w.seed(jar=b"new", expected=1) == 2
    # A late rotation for revision 1 must not land on revision 2.
    status = await w.states.get(SITE)
    stale = SiteSessionSecret(replace(status, seed_revision=1, jar_version=0), b"")
    await w.broker._absorb(stale, b"old", BrowserReport(O.VERIFIED, jar=b"late"))
    assert await stored_jar(w) == b"new"

    await w.secrets.revoke(SITE, expected_seed_revision=2)
    await w.broker.scan()
    await w.broker.scan()
    assert w.browser.forgotten == [SITE]


async def test_undecryptable_import_requires_reimport(world):
    w = world
    await w.secrets.seed(
        SITE,
        provider_key=None,
        expected_seed_revision=0,
        ciphertext=SiteSessionCipher(Fernet.generate_key().decode()).encrypt(
            SITE, 1, 0, b"x"
        ),
        egress_route="default",
    )
    await w.broker.scan()
    status = await w.states.get(SITE)
    assert status.state is S.RESEED_REQUIRED
    assert status.last_error_code == "session_undecryptable"
    assert w.browser.bootstrapped == []
