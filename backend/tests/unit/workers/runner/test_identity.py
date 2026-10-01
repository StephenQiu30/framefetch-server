"""Transport validation, operation privacy, policy and all cleanup paths."""

import asyncio
import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from app.services.provider_failures import FailureClass
from app.workers.runner.engine import identity
from app.workers.runner.engine.layers.base import LayerFailure
from pydantic import SecretStr

TOKEN = "unit-test-only-identity-token-32-bytes"
COOKIES = (
    b"# Netscape HTTP Cookie File\n"
    b".instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tsynthetic\n"
)


def deadline():
    return datetime.now(UTC) + timedelta(seconds=30)


@pytest.fixture
def transport(tmp_path, monkeypatch):
    root = tmp_path / "framefetch-identity"
    settings = SimpleNamespace(
        cookie_source_token=SecretStr(TOKEN),
        cookie_source_port=19101,
        runner_egress_proxy="http://proxy:3128",
        runner_identity_tmpfs_root=root,
    )
    monkeypatch.setattr(identity, "get_runner_settings", lambda: settings)
    monkeypatch.setattr(identity, "_is_tmpfs", lambda _: True)
    requests = []
    reply = {"cookies": base64.b64encode(COOKIES).decode(), "digest": "a" * 64}
    state = SimpleNamespace(status=200, reply=reply, block=False)

    async def respond(request):
        requests.append(request)
        assert request.url == "http://host.docker.internal:19101/cookies"
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        if state.block:
            await asyncio.Future()
        return httpx.Response(state.status, json=state.reply)

    client = httpx.AsyncClient

    def factory(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        assert kwargs.pop("proxy") == settings.runner_egress_proxy
        return client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(identity.httpx, "AsyncClient", factory)
    return root, settings, state, requests


async def test_material_private_operation_file_and_cleanup(transport):
    root, _, _, requests = transport
    async with identity.operation_identity(
        "instagram", "same-task", deadline()
    ) as material:
        assert material.cookie_file.read_bytes() == COOKIES
        assert material.cookie_file.stat().st_mode & 0o777 == 0o600
        assert material.cookie_file.parent.stat().st_mode & 0o777 == 0o700
        assert root.stat().st_mode & 0o777 == 0o700
        assert "cookies.txt" not in repr(material)
    assert list(root.iterdir()) == [] and len(requests) == 1


async def test_operations_of_same_task_do_not_reuse_material(transport):
    a = await identity.fetch_identity("instagram", "same-task", deadline())
    b = await identity.fetch_identity("instagram", "same-task", deadline())
    assert a.cookie_file != b.cookie_file
    a.cleanup()
    assert b.cookie_file.exists()
    b.cleanup()


@pytest.mark.parametrize("status", [401, 503, 302])
async def test_host_refusal_and_redirects_delete_operation(transport, status):
    root, _, state, _ = transport
    state.status = status
    with pytest.raises(LayerFailure) as error:
        await identity.fetch_identity("instagram", "task", deadline())
    assert error.value.failure.failure_class is FailureClass.IDENTITY_UNAVAILABLE
    assert list(root.iterdir()) == []


@pytest.mark.parametrize(
    "cookies,digest",
    [
        (COOKIES.replace(b"instagram.com", b"evil.com"), "a" * 64),
        (COOKIES.replace(b"\t0\t", b"\t1\t"), "a" * 64),
        (COOKIES, b"invalid".decode()),
        (b"invalid-cookie", "a" * 64),
    ],
)
async def test_invalid_expired_or_foreign_material_is_never_retained(
    transport, cookies, digest
):
    root, _, state, _ = transport
    state.reply = {"cookies": base64.b64encode(cookies).decode(), "digest": digest}
    with pytest.raises(LayerFailure):
        await identity.fetch_identity("instagram", "task", deadline())
    assert list(root.iterdir()) == []


async def test_non_tmpfs_and_symlink_roots_fail_closed(
    transport, monkeypatch, tmp_path
):
    root, settings, _, requests = transport
    monkeypatch.setattr(identity, "_is_tmpfs", lambda _: False)
    with pytest.raises(LayerFailure):
        await identity.fetch_identity("instagram", "task", deadline())
    assert not requests
    outside = tmp_path / "outside"
    outside.mkdir()
    settings.runner_identity_tmpfs_root = tmp_path / "sym" / "framefetch-identity"
    (tmp_path / "sym").symlink_to(outside, target_is_directory=True)
    with pytest.raises(LayerFailure):
        identity.initialize_identity_tmpfs(settings.runner_identity_tmpfs_root)
    assert list(outside.iterdir()) == []


async def test_startup_cleanup_removes_crash_residue_without_following_symlinks(
    transport, tmp_path
):
    root, _, _, _ = transport
    root.mkdir(mode=0o700)
    (root / "aborted-op").mkdir()
    (root / "aborted-op" / "cookies.txt").write_bytes(COOKIES)
    protected = tmp_path / "keep"
    protected.write_text("keep")
    (root / "link").symlink_to(protected)
    identity.initialize_identity_tmpfs(root)
    assert list(root.iterdir()) == [] and protected.read_text() == "keep"


async def test_cancel_during_transport_cleans_operation(transport):
    root, _, state, requests = transport
    state.block = True
    task = asyncio.create_task(identity.fetch_identity("instagram", "task", deadline()))
    while not requests:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
async def test_exception_and_cancellation_after_injection_cleanup(transport, error):
    root, _, _, _ = transport
    with pytest.raises(error):
        async with identity.operation_identity("instagram", "task", deadline()):
            raise error()
    assert list(root.iterdir()) == []


async def test_required_every_operation_optional_once_after_evidence_none_never(
    transport, monkeypatch
):
    root, _, _, _ = transport
    fetched = AsyncMock(wraps=identity.fetch_identity)
    monkeypatch.setattr(identity, "fetch_identity", fetched)
    for _ in range(2):
        async with identity.IdentityOperation(
            "instagram", "task", deadline()
        ) as operation:
            assert operation.material
            assert not await operation.after_login_required()
    assert fetched.await_count == 2

    # Policy only: fake the material transport for a declared optional site.
    async def optional(site, task, end):
        return await fetched("instagram", task, end)

    monkeypatch.setattr(identity, "fetch_identity", optional)
    async with identity.IdentityOperation("bilibili", "task", deadline()) as operation:
        assert operation.material is None
        assert fetched.await_count == 2
        assert await operation.after_login_required()
        assert not await operation.after_login_required()
    async with identity.IdentityOperation("tiktok", "task", deadline()) as operation:
        assert operation.material is None
        assert not await operation.after_login_required()
    assert fetched.await_count == 3 and list(root.iterdir()) == []


async def test_none_direct_fetch_and_expired_deadline_never_call_host(transport):
    _, _, _, requests = transport
    for site, end in [("tiktok", deadline()), ("instagram", datetime.now(UTC))]:
        with pytest.raises(LayerFailure):
            await identity.fetch_identity(site, "task", end)
    assert requests == []


async def test_optional_identity_failure_is_terminal_and_not_retried(
    transport, monkeypatch
):
    fetched = AsyncMock(side_effect=identity._unavailable("extension_disconnected"))
    monkeypatch.setattr(identity, "fetch_identity", fetched)
    async with identity.IdentityOperation("bilibili", "task", deadline()) as operation:
        with pytest.raises(LayerFailure):
            await operation.after_login_required()
        assert not await operation.after_login_required()
    assert fetched.await_count == 1


async def test_runner_lifespan_clears_tmpfs_before_accepting_requests(transport):
    from app.workers.runner.main import create_app
    from app.workers.runner.settings import RunnerSettings

    root, _, _, _ = transport
    root.mkdir(mode=0o700)
    (root / "crashed").mkdir()
    (root / "crashed" / "cookies.txt").write_bytes(COOKIES)
    settings = RunnerSettings(
        runner_hmac_secret=SecretStr("h" * 32),
        runner_egress_proxy="http://proxy:3128",
        runner_identity_tmpfs_root=root,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        assert list(root.iterdir()) == []


@pytest.mark.parametrize(
    "cause", ["extension_disconnected", "extension_timeout", "credential_missing"]
)
async def test_extension_subcause_survives_runner_failure(transport, cause):
    root, _, state, _ = transport
    state.status, state.reply = 503, {"cause": cause}
    with pytest.raises(LayerFailure) as error:
        await identity.fetch_identity("instagram", "task", deadline())
    assert error.value.failure.evidence["cause_code"] == cause
    assert list(root.iterdir()) == []


async def test_host_error_cannot_leak_arbitrary_cause(transport):
    root, _, state, _ = transport
    state.status, state.reply = 503, {"cause": "private-material"}
    with pytest.raises(LayerFailure) as error:
        await identity.fetch_identity("instagram", "task", deadline())
    assert error.value.failure.evidence["cause_code"] == "cookie_source_rejected"
    assert list(root.iterdir()) == []
