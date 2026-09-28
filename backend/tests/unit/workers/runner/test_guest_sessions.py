from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from app.services.provider_guest import GuestScope
from app.services.provider_types import ProviderAccessMode, ProviderKey
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.guest_material import (
    publish_guest_lease,
    read_guest_lease,
    validate_guest_material,
)
from app.workers.runner.provider_registry import provider_profile_for_key
from app.workers.runner.provider_sessions import ProviderSessionStore
from app.workers.runner.settings import RunnerSettings
from pydantic import ValidationError

COOKIE = (
    b"# Netscape HTTP Cookie File\n"
    b".iesdouyin.com\tTRUE\t/\tTRUE\t2147483647\tttwid\tfixture-guest\n"
)


def settings(tmp_path):
    return RunnerSettings(
        runner_hmac_secret="x" * 32,
        runner_egress_proxy="http://proxy:3128",
        runner_workspace_root=tmp_path / "work",
        runner_access_mode="guest",
        runner_guest_provider="douyin",
        runner_guest_cookie_file=tmp_path / "cookies.txt",
        runner_provider_session_temp_root=tmp_path / "session",
        runner_credential_lease_redis_url="redis://localhost:6379/0",
        runner_max_active_tasks=1,
    )


def scope(config):
    profile = provider_profile_for_key("douyin")
    return GuestScope(
        ProviderKey.DOUYIN,
        profile.version,
        profile.client_profile_id,
        config.egress_affinity_for("douyin"),
    )


class Lease:
    async def ping(self):
        pass

    async def close(self):
        pass

    @asynccontextmanager
    async def hold(self, provider, revision):
        assert provider == "douyin" and revision == "public-guest"
        yield


async def test_guest_runner_only_reads_scoped_lease_and_cleans_operation(tmp_path):
    config = settings(tmp_path)
    key = scope(config)
    now = datetime.now(UTC)
    publish_guest_lease(
        config.runner_guest_cookie_file,
        key,
        1,
        COOKIE,
        now=now,
        deadline=now + timedelta(seconds=80),
    )
    store = ProviderSessionStore(
        config, credential_lease=Lease(), enforce_memory_backing=False
    )
    assert await store.is_ready()
    context = await store.context_for(provider_profile_for_key("douyin"))
    assert context.access_mode is ProviderAccessMode.GUEST
    async with store.operation(context) as jar:
        assert jar.read_bytes() == COOKIE
        assert jar.stat().st_mode & 0o777 == 0o600
    assert not jar.exists()
    with pytest.raises(RunnerFailure):
        await store.context_for(provider_profile_for_key("youtube"))
    publish_guest_lease(
        config.runner_guest_cookie_file,
        key,
        2,
        COOKIE,
        now=now,
        deadline=now + timedelta(seconds=80),
    )
    with pytest.raises(RunnerFailure):
        async with store.operation(context):
            pytest.fail("stale guest revision entered execution")
    refreshed = await store.validate_context(
        provider_profile_for_key("douyin"), context, allow_guest_refresh=True
    )
    assert refreshed.credential_version_id == "guest-2"
    for changed in (
        replace(context, engine_commit="another-engine"),
        replace(context, egress_affinity_id="another-egress"),
        replace(context, profile_version="another-profile"),
        replace(context, client_profile_id="another-client"),
        replace(context, access_mode=ProviderAccessMode.OPERATOR_MANAGED),
    ):
        with pytest.raises(RunnerFailure):
            await store.validate_context(
                provider_profile_for_key("douyin"), changed, allow_guest_refresh=True
            )
    await store.close()


@pytest.mark.parametrize(
    "extra",
    [
        b".douyin.com\tTRUE\t/\tTRUE\t2147483647\tsessionid\taccount\n",
        b".douyin.com\tTRUE\t/\tTRUE\t2147483647\tsessionid\t\n",
        b".example.com\tTRUE\t/\tTRUE\t2147483647\tttwid\tcross-site\n",
    ],
)
def test_guest_material_rejects_account_or_cross_platform_cookie(tmp_path, extra):
    with pytest.raises(RunnerFailure):
        validate_guest_material(
            scope(settings(tmp_path)), COOKIE + extra, now=datetime.now(UTC)
        )


def test_guest_lease_expiry_scope_permissions_and_no_raw_file_fallback(tmp_path):
    config = settings(tmp_path)
    key = scope(config)
    now = datetime.now(UTC)
    path = config.runner_guest_cookie_file
    path.write_bytes(COOKIE)
    path.chmod(0o600)
    with pytest.raises(RunnerFailure):
        read_guest_lease(path, key, now=now)
    publish_guest_lease(
        path, key, 1, COOKIE, now=now, deadline=now + timedelta(seconds=60)
    )
    for changed in (
        replace(key, provider=ProviderKey.WEIBO),
        replace(key, egress_affinity_id="other"),
    ):
        with pytest.raises(RunnerFailure):
            read_guest_lease(path, changed, now=now)
    with pytest.raises(RunnerFailure):
        read_guest_lease(path, key, now=now + timedelta(seconds=61))
    path.chmod(0o644)
    with pytest.raises(RunnerFailure):
        read_guest_lease(path, key, now=now)


def test_anonymous_runner_cannot_mount_guest_material(tmp_path):
    values = settings(tmp_path).model_dump()
    values["runner_access_mode"] = "anonymous"
    with pytest.raises(ValidationError, match="only a guest runner"):
        RunnerSettings(**values)
