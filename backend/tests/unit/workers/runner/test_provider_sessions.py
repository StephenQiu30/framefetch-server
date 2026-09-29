from __future__ import annotations

import os
import stat
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import pytest
from app.services.provider_types import ProviderAccessMode
from app.workers.runner import provider_session_files
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import provider_profile
from app.workers.runner.provider_sessions import ProviderSessionStore
from app.workers.runner.settings import RunnerSettings
from app.workers.runner.site_sessions import OperationSession
from pydantic import ValidationError

SECRET = "runner-shared-secret-material-at-least-32-bytes"
COOKIE = (
    b"# Netscape HTTP Cookie File\n"
    b".youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tfixture-secret\n"
)
YOUTUBE = "https://www.youtube.com/watch?v=owned"


class FakeSiteSessions:
    def __init__(self) -> None:
        self.revisions: dict[str, int] = {"youtube.com": 3, "example.co.uk": 1}
        self.leases: list[tuple[str, int]] = []
        self.reports: list[tuple[str, int, str]] = []
        self.closed = False
        self.rotations = []

    async def ready_revision(self, site: str) -> int:
        if site not in self.revisions:
            raise RunnerFailure("provider_session_not_ready", status=503)
        return self.revisions[site]

    async def lease(self, site: str, seed_revision: int) -> OperationSession:
        self.leases.append((site, seed_revision))
        return OperationSession(
            "operation", site, seed_revision, 2147483647, "unused", COOKIE
        )

    async def rotate(self, operation, payload):
        self.rotations.append((operation, payload))

    async def report(self, site: str, seed_revision: int, error_code: str) -> None:
        self.reports.append((site, seed_revision, error_code))

    async def close(self) -> None:
        self.closed = True


class FakeCredentialLease:
    def __init__(self) -> None:
        self.held: list[tuple[str, str]] = []

    @asynccontextmanager
    async def hold(self, provider: str, version: str, *, wait_seconds: float = 0):
        self.held.append((provider, version))
        yield

    async def ping(self) -> None:
        pass

    async def close(self) -> None:
        pass


def anonymous_settings(tmp_path: Path) -> RunnerSettings:
    return RunnerSettings(
        runner_hmac_secret=SECRET,
        runner_egress_proxy="http://egress-proxy:3128",
        runner_workspace_root=tmp_path,
    )


def session_settings(tmp_path: Path, **overrides) -> RunnerSettings:
    values = dict(
        runner_hmac_secret=SECRET,
        runner_egress_proxy="http://egress-proxy:3128",
        runner_workspace_root=tmp_path / "work",
        runner_access_mode=ProviderAccessMode.OPERATOR_MANAGED,
        runner_provider_session_temp_root=tmp_path / "session-tmp",
        runner_session_broker_url="http://session-broker:19200",
        runner_session_rpc_secret="r" * 32,
        runner_credential_lease_redis_url="redis://provider-lease-redis:6379/0",
    )
    values.update(overrides)
    return RunnerSettings(**values)


def session_store(tmp_path: Path):
    sessions, lease = FakeSiteSessions(), FakeCredentialLease()
    store = ProviderSessionStore(
        session_settings(tmp_path),
        credential_lease=lease,
        site_sessions=sessions,
        enforce_memory_backing=False,
    )
    return store, sessions, lease


async def test_runtime_change_between_lookup_and_download_is_retryable(
    tmp_path: Path,
) -> None:
    store = ProviderSessionStore(anonymous_settings(tmp_path))
    profile = provider_profile(YOUTUBE)
    current = await store.context_for(profile)
    prior = replace(current, runtime_revision="0" * 64)

    with pytest.raises(RunnerFailure) as caught:
        await store.validate_context(profile, prior)

    assert caught.value.code == "runner_release_changed"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"runner_session_broker_url": None}, "requires the broker URL and secret"),
        ({"runner_session_rpc_secret": "short"}, "requires the broker URL and secret"),
        (
            {"runner_credential_lease_redis_url": None},
            "requires distributed execution leases",
        ),
        (
            {"runner_access_mode": ProviderAccessMode.ANONYMOUS},
            "only the session runner may reach the session broker",
        ),
    ],
)
def test_session_runner_settings_fail_closed(
    tmp_path: Path, overrides: dict, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        session_settings(tmp_path, **overrides)


def test_settings_reject_session_tmpfs_inside_shared_workspace(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError, match="cannot be in the workspace"):
        RunnerSettings(
            runner_hmac_secret=SECRET,
            runner_egress_proxy="http://egress-proxy:3128",
            runner_workspace_root=tmp_path / "work",
            runner_provider_session_temp_root=tmp_path / "work" / "sessions",
        )


def test_session_root_must_be_memory_backed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "memory session"
    root.mkdir()
    mountinfo = tmp_path / "mountinfo"
    escaped = str(root).replace(" ", r"\040")
    mountinfo.write_text(
        f"41 31 0:38 / {escaped} rw,nosuid - tmpfs tmpfs rw\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(provider_session_files.sys, "platform", "linux")

    provider_session_files.require_memory_backed_root(root, mountinfo=mountinfo)

    mountinfo.write_text(
        f"41 31 0:38 / {escaped} rw - ext4 /dev/disk rw\n",
        encoding="utf-8",
    )
    with pytest.raises(RunnerFailure) as caught:
        provider_session_files.require_memory_backed_root(root, mountinfo=mountinfo)

    assert caught.value.code == "provider_session_unavailable"


async def test_session_context_freezes_site_and_ready_revision(tmp_path: Path) -> None:
    store, sessions, _ = session_store(tmp_path)

    context = await store.context_for(provider_profile(YOUTUBE), url=YOUTUBE)
    by_key = await store.context_for(provider_profile(YOUTUBE))

    assert context.access_mode is ProviderAccessMode.OPERATOR_MANAGED
    assert context.credential_version_id == "youtube.com:3"
    assert by_key == context
    # Unlisted sites use the same route, keyed by registrable domain.
    unlisted = "https://media.example.co.uk/v/1"
    generic = await store.context_for(provider_profile(unlisted), url=unlisted)
    assert generic.provider_key == "generic"
    assert generic.credential_version_id == "example.co.uk:1"

    sessions.revisions.pop("youtube.com")
    with pytest.raises(RunnerFailure) as caught:
        await store.context_for(provider_profile(YOUTUBE), url=YOUTUBE)
    assert caught.value.code == "provider_session_not_ready"
    with pytest.raises(RunnerFailure) as caught:
        await store.context_for(provider_profile(unlisted))
    assert caught.value.code == "provider_session_not_allowed"


async def test_reimport_makes_a_frozen_context_stale(tmp_path: Path) -> None:
    store, sessions, _ = session_store(tmp_path)
    profile = provider_profile(YOUTUBE)
    context = await store.context_for(profile, url=YOUTUBE)

    sessions.revisions["youtube.com"] = 4
    with pytest.raises(RunnerFailure) as caught:
        await store.validate_context(profile, context, url=YOUTUBE)

    assert caught.value.code == "credential_revoked"


async def test_operation_holds_the_site_lease_and_uses_a_private_tmpfs_file(
    tmp_path: Path,
) -> None:
    store, sessions, lease = session_store(tmp_path)
    settings = session_settings(tmp_path)
    context = await store.context_for(provider_profile(YOUTUBE), url=YOUTUBE)

    async with store.operation(context) as jar:
        assert jar is not None
        operation_path = jar
        assert jar.parent.parent == settings.runner_provider_session_temp_root
        assert jar.read_bytes() == COOKIE
        if os.name == "posix":
            assert stat.S_IMODE(jar.stat().st_mode) == 0o600
            assert stat.S_IMODE(jar.parent.stat().st_mode) == 0o700

    assert sessions.leases == [("youtube.com", 3)]
    assert lease.held == [("youtube.com", "session")]
    assert not operation_path.exists()
    assert list(settings.runner_provider_session_temp_root.iterdir()) == []


async def test_failures_are_reported_to_the_broker_for_session_contexts_only(
    tmp_path: Path,
) -> None:
    store, sessions, _ = session_store(tmp_path)
    context = await store.context_for(provider_profile(YOUTUBE), url=YOUTUBE)

    await store.report_failure(context, "egress_challenged")
    await store.report_failure(
        replace(context, credential_version_id="malformed"), "egress_challenged"
    )
    anonymous = await ProviderSessionStore(anonymous_settings(tmp_path)).context_for(
        provider_profile(YOUTUBE)
    )
    await store.report_failure(anonymous, "egress_challenged")

    assert sessions.reports == [("youtube.com", 3, "egress_challenged")]
    await store.close()
    assert sessions.closed


async def test_malformed_session_version_is_revoked(tmp_path: Path) -> None:
    store, _, _ = session_store(tmp_path)
    context = await store.context_for(provider_profile(YOUTUBE), url=YOUTUBE)

    with pytest.raises(RunnerFailure) as caught:
        async with store.operation(replace(context, credential_version_id="x")):
            pass

    assert caught.value.code == "credential_revoked"


async def test_native_public_operation_uses_no_credentials_or_broker(tmp_path):
    broker = FakeSiteSessions()
    locks = FakeCredentialLease()
    store = ProviderSessionStore(
        session_settings(tmp_path),
        site_sessions=broker,
        credential_lease=locks,
        enforce_memory_backing=False,
    )
    profile = provider_profile("https://t.me/example/1")
    context = await store.context_for(profile)
    assert context.access_mode is ProviderAccessMode.ANONYMOUS
    assert context.credential_version_id is None
    async with store.operation(context) as jar:
        assert jar is None
    assert not broker.leases and not locks.held
    forged = replace(context, provider_key="youtube")
    with pytest.raises(RunnerFailure, match="provider session not allowed"):
        async with store.operation(forged):
            pytest.fail("session platforms may never execute without a lease")
