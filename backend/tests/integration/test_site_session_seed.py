import time
from http.cookiejar import Cookie

import pytest
from app.core.security.site_session_cipher import SiteSessionCipher
from app.integrations.site_session_catalog import site_target_for_host
from app.repositories.providers.site_sessions import (
    SiteSessionSecrets,
    SiteSessionStates,
)
from app.services.site_sessions import SiteSessionState
from app.workers.runner.netscape_cookie import live_cookie_payload
from app.workers.session import source
from app.workers.session.chrome_reader import ChromeProfile
from app.workers.session.seed import (
    SeedChoice,
    SeedError,
    import_session,
    revoke_session,
)
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import async_sessionmaker

TARGET = site_target_for_host("youtu.be")


def choice(value: str) -> SeedChoice:
    cookies = tuple(
        Cookie(
            0,
            name,
            value,
            None,
            False,
            ".youtube.com",
            True,
            True,
            "/",
            True,
            True,
            int(time.time()) + 3600,
            False,
            None,
            None,
            {},
            False,
        )
        for name in ("SAPISID", "__Secure-3PSID")
    )
    return SeedChoice(ChromeProfile("Default", "Me"), cookies)


async def test_import_reimport_and_revoke(postgres_engine):
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    states, secrets = SiteSessionStates(sessions), SiteSessionSecrets(sessions)
    cipher = SiteSessionCipher(Fernet.generate_key().decode())
    deps = dict(states=states, secrets=secrets, cipher=cipher)

    assert await import_session(TARGET, choice("one"), **deps) == 1
    assert await import_session(TARGET, choice("two"), **deps) == 2
    stored = await secrets.read("youtube.com")
    assert stored.status.provider_key == "youtube"
    assert stored.status.state is SiteSessionState.SEEDED
    payload = cipher.decrypt("youtube.com", 2, 0, stored.ciphertext)
    _, names = live_cookie_payload(payload, TARGET.cookie_domains)
    assert names == {"SAPISID", "__Secure-3PSID"} and b"\ttwo" in payload

    revoked = await revoke_session("youtube.com", states=states, secrets=secrets)
    assert revoked.seed_revision == 2
    assert (await states.get("youtube.com")).state is SiteSessionState.REVOKED
    with pytest.raises(SeedError):
        await revoke_session("youtube.com", states=states, secrets=secrets)
    assert await import_session(TARGET, choice("three"), **deps) == 3


async def test_automatic_source_lifecycle(postgres_engine, monkeypatch):
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    states, secrets = SiteSessionStates(sessions), SiteSessionSecrets(sessions)
    cipher = SiteSessionCipher(Fernet.generate_key().decode())
    deps = dict(states=states, secrets=secrets, cipher=cipher)
    selected = choice("one")
    profiles = []

    def read(target, *, profile):
        profiles.append(profile)
        return selected

    monkeypatch.setattr(source, "select_seed", read)
    assert (
        await source.reconcile_site(TARGET.site, **deps)
        == "imported_pending_verification"
    )
    stored = await secrets.read(TARGET.site)
    assert stored.source_profile == "Default"
    assert len(stored.source_fingerprint) == 64
    assert profiles == [None]
    # No browser read while the broker owns an active session.
    for state in (
        SiteSessionState.SEEDED,
        SiteSessionState.VERIFYING,
        SiteSessionState.READY,
        SiteSessionState.DEGRADED,
    ):
        current = await states.get(TARGET.site)
        await secrets.transition(
            TARGET.site, seed_revision=1, allowed_from={current.state}, to=state
        )
        assert await source.reconcile_site(TARGET.site, **deps) == state.value
    assert profiles == [None]
    await secrets.transition(
        TARGET.site,
        seed_revision=1,
        allowed_from={SiteSessionState.DEGRADED},
        to=SiteSessionState.RESEED_REQUIRED,
    )
    # Source instance restart cannot replay the same rejected login.
    for _ in range(2):
        assert await source.reconcile_site(TARGET.site, **deps) == "awaiting_new_login"
    assert (await states.get(TARGET.site)).seed_revision == 1
    assert profiles == [None, "Default", "Default"]
    assert (
        await source.reconcile_site(TARGET.site, profile="Profile 2", **deps)
        == "profile_change_requires_import"
    )
    assert len(profiles) == 3
    # A newly authenticated Chrome login is imported without an operator command.
    selected = choice("new-login")
    assert (
        await source.reconcile_site(TARGET.site, **deps)
        == "imported_pending_verification"
    )
    assert (await states.get(TARGET.site)).seed_revision == 2
    await secrets.revoke(TARGET.site, expected_seed_revision=2)
    assert await source.reconcile_site(TARGET.site, **deps) == "revoked"
    assert len(profiles) == 4


@pytest.mark.parametrize(
    "changed_to", [SiteSessionState.REVOKED, SiteSessionState.READY]
)
async def test_automatic_import_cannot_overwrite_concurrent_decision(
    postgres_engine, monkeypatch, changed_to
):
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    states, secrets = SiteSessionStates(sessions), SiteSessionSecrets(sessions)
    cipher = SiteSessionCipher(Fernet.generate_key().decode())
    deps = dict(states=states, secrets=secrets, cipher=cipher)
    await import_session(TARGET, choice("old"), **deps)
    await secrets.transition(
        TARGET.site,
        seed_revision=1,
        allowed_from={SiteSessionState.SEEDED},
        to=SiteSessionState.RESEED_REQUIRED,
    )
    monkeypatch.setattr(source, "select_seed", lambda *a, **k: choice("new"))

    async def concurrent(*args, **kwargs):
        if changed_to is SiteSessionState.REVOKED:
            await secrets.revoke(TARGET.site, expected_seed_revision=1)
        else:
            await secrets.transition(
                TARGET.site,
                seed_revision=1,
                allowed_from={SiteSessionState.RESEED_REQUIRED},
                to=changed_to,
            )
        return await import_session(*args, **kwargs)

    monkeypatch.setattr(source, "import_session", concurrent)
    assert await source.reconcile_site(TARGET.site, **deps) == "changed_concurrently"
    current = await states.get(TARGET.site)
    assert current.state is changed_to and current.seed_revision == 1


async def test_two_automatic_sources_only_import_once(postgres_engine, monkeypatch):
    import asyncio

    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    states, secrets = SiteSessionStates(sessions), SiteSessionSecrets(sessions)
    cipher = SiteSessionCipher(Fernet.generate_key().decode())
    monkeypatch.setattr(source, "select_seed", lambda *a, **k: choice("one"))
    await asyncio.gather(
        *(
            source.reconcile_site(
                TARGET.site, states=states, secrets=secrets, cipher=cipher
            )
            for _ in range(2)
        )
    )
    assert (await states.get(TARGET.site)).seed_revision == 1
