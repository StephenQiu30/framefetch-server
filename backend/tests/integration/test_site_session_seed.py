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
