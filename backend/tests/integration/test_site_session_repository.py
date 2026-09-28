import asyncio
from pathlib import Path

import pytest
from app.repositories.providers.site_sessions import (
    SiteSessionConflict,
    SiteSessionSecrets,
    SiteSessionStates,
)
from app.services.site_sessions import SiteSessionState
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.postgres import isolated_postgres_engine

SITE = "youtube.com"
LIVE = frozenset(SiteSessionState) - {SiteSessionState.REVOKED}


def repositories(engine):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    return SiteSessionStates(sessions), SiteSessionSecrets(sessions)


async def seed(secrets, expected=0, value=b"seed", site=SITE):
    return await secrets.seed(
        site,
        provider_key="youtube",
        expected_seed_revision=expected,
        ciphertext=value,
        egress_route="default",
    )


async def test_concurrent_first_imports_have_one_winner(postgres_engine):
    states, secrets = repositories(postgres_engine)
    results = await asyncio.gather(
        *(seed(secrets, value=f"s{i}".encode()) for i in range(20)),
        return_exceptions=True,
    )
    assert sum(result == 1 for result in results) == 1
    assert all(
        isinstance(result, SiteSessionConflict) for result in results if result != 1
    )
    status = await states.get(SITE)
    assert status.state is SiteSessionState.SEEDED
    assert (status.seed_revision, status.jar_version) == (1, 0)


async def test_keepalive_cannot_overwrite_a_newer_import(postgres_engine):
    states, secrets = repositories(postgres_engine)
    await seed(secrets)
    assert (
        await secrets.publish_jar(
            SITE, seed_revision=1, expected_jar_version=0, ciphertext=b"jar1"
        )
        == 1
    )
    with pytest.raises(SiteSessionConflict):
        await secrets.publish_jar(
            SITE, seed_revision=1, expected_jar_version=0, ciphertext=b"stale"
        )
    assert await seed(secrets, expected=1, value=b"reseed") == 2
    with pytest.raises(SiteSessionConflict):
        await secrets.publish_jar(
            SITE, seed_revision=1, expected_jar_version=1, ciphertext=b"late"
        )
    secret = await secrets.read(SITE)
    assert secret.ciphertext == b"reseed"
    assert (secret.status.seed_revision, secret.status.jar_version) == (2, 0)
    assert (await states.get(SITE)).refreshed_at is None


async def test_state_transitions_are_conditional(postgres_engine):
    states, secrets = repositories(postgres_engine)
    await seed(secrets)
    await secrets.transition(
        SITE,
        seed_revision=1,
        allowed_from={SiteSessionState.SEEDED},
        to=SiteSessionState.VERIFYING,
    )
    await secrets.transition(
        SITE,
        seed_revision=1,
        allowed_from={SiteSessionState.VERIFYING},
        to=SiteSessionState.READY,
        verified=True,
    )
    ready = await states.get(SITE)
    assert ready.state is SiteSessionState.READY and ready.verified_at is not None
    with pytest.raises(SiteSessionConflict):
        await secrets.transition(
            SITE,
            seed_revision=1,
            allowed_from={SiteSessionState.VERIFYING},
            to=SiteSessionState.READY,
        )
    await secrets.transition(
        SITE,
        seed_revision=1,
        allowed_from=LIVE,
        to=SiteSessionState.DEGRADED,
        error_code="credential_expired",
    )
    degraded = await states.get(SITE)
    assert degraded.last_error_code == "credential_expired"
    assert degraded.verified_at == ready.verified_at
    with pytest.raises(ValueError):
        await secrets.transition(
            SITE, seed_revision=1, allowed_from=LIVE, to=SiteSessionState.REVOKED
        )


async def test_revocation_is_a_tombstone_that_only_a_new_import_replaces(
    postgres_engine,
):
    states, secrets = repositories(postgres_engine)
    await seed(secrets)
    await secrets.revoke(SITE, expected_seed_revision=1)
    assert await secrets.read(SITE) is None
    revoked = await states.get(SITE)
    assert revoked.state is SiteSessionState.REVOKED and revoked.seed_revision == 1
    with pytest.raises(SiteSessionConflict):
        await secrets.revoke(SITE, expected_seed_revision=1)
    with pytest.raises(SiteSessionConflict):
        await secrets.publish_jar(
            SITE, seed_revision=1, expected_jar_version=0, ciphertext=b"late"
        )
    with pytest.raises(SiteSessionConflict):
        await secrets.transition(
            SITE,
            seed_revision=1,
            allowed_from=LIVE,
            to=SiteSessionState.READY,
        )
    assert await seed(secrets, expected=1, value=b"again") == 2
    assert (await states.get(SITE)).state is SiteSessionState.SEEDED


async def test_status_reader_never_selects_ciphertext(postgres_engine):
    states, secrets = repositories(postgres_engine)
    await seed(secrets, site="example.co.uk")
    statements: list[str] = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    from sqlalchemy import event

    event.listen(postgres_engine.sync_engine, "before_cursor_execute", record)
    try:
        assert [status.site for status in await states.list()] == ["example.co.uk"]
        assert (await states.get("example.co.uk")).provider_key == "youtube"
    finally:
        event.remove(postgres_engine.sync_engine, "before_cursor_execute", record)
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert selects and not any("ciphertext" in s for s in selects)


async def test_schema_is_idempotent_and_enforces_tombstones() -> None:
    sql = (Path(__file__).resolve().parents[2] / "sql/schema.sql").read_text()
    async with isolated_postgres_engine() as engine:
        async with engine.connect() as connection:
            schema = await connection.scalar(text("SELECT current_schema()"))
            await connection.execute(text(f'SET search_path TO "{schema}", public'))
            await connection.commit()
            driver = (await connection.get_raw_connection()).driver_connection
            await driver.execute(sql)
            await driver.execute(
                "INSERT INTO site_sessions (site, state, seed_revision, ciphertext, "
                "egress_route, seeded_at, state_changed_at) "
                "VALUES ('example.com', 'revoked', 3, NULL, 'default', now(), now())"
            )
            await driver.execute(sql)
            row = await driver.fetchrow("SELECT * FROM site_sessions")
            assert row["seed_revision"] == 3 and row["ciphertext"] is None
            with pytest.raises(Exception, match="ck_site_sessions_revoked"):
                await driver.execute(
                    "INSERT INTO site_sessions (site, state, seed_revision, "
                    "ciphertext, egress_route, seeded_at, state_changed_at) VALUES "
                    "('b.com', 'ready', 1, NULL, 'default', now(), now())"
                )
