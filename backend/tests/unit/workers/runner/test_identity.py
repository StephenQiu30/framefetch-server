"""Transport validation, operation privacy, policy and all cleanup paths."""

import asyncio
import base64
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from app.services.provider_failures import FailureClass
from app.services.provider_types import Layer
from app.workers.runner.commands import MediaCommands
from app.workers.runner.engine import identity
from app.workers.runner.engine.egress import EgressBinding
from app.workers.runner.engine.ladder import LAYER_TABLE, close_material, run_ladder
from app.workers.runner.engine.layers.base import LayerFailure
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import provider_request
from app.workers.runner.service import MediaRunnerService
from helpers import settings as runner_settings
from pydantic import SecretStr
from test_commands import RecordingSupervisor
from test_engine_skeleton import source_for
from test_p1_wiring import resolved

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
    state = SimpleNamespace(status=200, reply=reply, block=False, route="/cookies")

    async def respond(request):
        requests.append(request)
        assert request.url == f"http://host.docker.internal:19101{state.route}"
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


async def test_native_page_identity_cannot_use_cookie_transport(transport):
    root, _, _, requests = transport
    with pytest.raises(LayerFailure) as error:
        await identity.fetch_identity("wechat_channels", "task", deadline())
    assert error.value.failure.evidence["cause_code"] == "identity_not_declared"
    assert not requests and not root.exists()


def test_native_page_identity_contains_only_digest():
    material = identity.NativePageIdentity("a" * 64)
    material.cleanup()
    assert not hasattr(material, "cookie_file")
    with pytest.raises(ValueError):
        identity.NativePageIdentity("invalid")


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


async def test_none_direct_fetch_and_expired_deadline_never_call_host(transport):
    _, _, _, requests = transport
    for site, end in [("tiktok", deadline()), ("instagram", datetime.now(UTC))]:
        with pytest.raises(LayerFailure):
            await identity.fetch_identity(site, "task", end)
    assert requests == []


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
    "cause",
    [
        "extension_disconnected",
        "extension_timeout",
        "credential_missing",
        "identity_material_invalid",
        "identity_cookie_name_invalid",
        "identity_cookie_encoding_invalid",
        "identity_cookie_value_invalid",
        "identity_cookie_payload_invalid",
    ],
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


@pytest.mark.parametrize("site", ["instagram", "bilibili"])
@pytest.mark.parametrize("success", [True, False])
@pytest.mark.parametrize("binding_mode", ["injected", "resolved"])
async def test_ladder_uses_real_identity_transport_and_separate_media_binding(
    transport, tmp_path, monkeypatch, site, success, binding_mode
):
    root, host_settings, state, requests = transport
    if site == "bilibili":
        state.reply["cookies"] = base64.b64encode(
            COOKIES.replace(b"instagram.com", b"bilibili.com")
        ).decode()
    monkeypatch.setattr(identity, "COOKIE_TMPFS_ROOT", root)
    monkeypatch.setattr(identity, "_on_tmpfs", lambda _: True)
    config = runner_settings(tmp_path)
    service = MediaRunnerService(config)
    source = source_for(service, tmp_path)
    request = provider_request(
        "https://www.instagram.com/p/example/"
        if site == "instagram"
        else "https://www.bilibili.com/video/BV13x41117TL"
    )
    binding = EgressBinding(
        "platform", "http://media-binding:3128", "revision", "residential", None
    )
    if binding_mode == "resolved":
        from app.workers.runner.engine.egress import resolve_egress

        config = config.model_copy(
            update={
                "runner_egress_proxy": "http://domestic-media:3128",
                "runner_global_egress_proxy": "http://global-media:3129",
                "egress_cn_upstream_host": "cn-residential",
                "egress_global_upstream_host": "global-residential",
            }
        )
        binding = resolve_egress(request.profile, settings=config)
        assert binding.route == (
            "cn_residential" if site == "bilibili" else "global_residential"
        )
        assert binding.egress_class == "residential"
    assert binding.proxy_url != host_settings.runner_egress_proxy
    source = replace(
        source,
        request=request,
        execution_context=service._context(request),
        run_context=replace(source.run_context, egress=binding),
    )
    supervisor = RecordingSupervisor()
    calls = []

    class LayerWithIdentity:
        async def resolve(self, item, ctx):
            calls.append(ctx.identity)
            assert ctx.identity is not None
            assert ctx.cookie_file == ctx.identity.cookie_file
            identity.validate_cookie_file(ctx.cookie_file)
            # Media IO still consumes P1's injected EgressBinding and Cookie path.
            await (
                MediaCommands(config, supervisor)
                .with_context(ctx)
                .inspect(item.request, item.workspace.path, cookie_jar=ctx.cookie_file)
            )
            assert (
                supervisor.argv[supervisor.argv.index("--proxy") + 1]
                == binding.proxy_url
            )
            assert supervisor.env["HTTPS_PROXY"] == binding.proxy_url
            assert supervisor.argv[supervisor.argv.index("--cookies") + 1] == str(
                ctx.cookie_file
            )
            if not success:
                raise LayerFailure(FailureClass.CONTENT_PROTECTED, "①", {})
            return resolved(ctx)

    monkeypatch.setitem(LAYER_TABLE, Layer.L1, LayerWithIdentity)
    result = None
    try:
        if success:
            result = await run_ladder(
                source, request.profile, source.run_context.deadline
            )
            assert result.execution_context.identity_used
            assert result.execution_context.identity_digest == "a" * 64
            assert result.execution_context.egress_route == binding.route
            assert result.run_context.identity is calls[-1]
            await close_material(result.run_context)
        else:
            with pytest.raises(RunnerFailure) as caught:
                await run_ladder(source, request.profile, source.run_context.deadline)
            assert caught.value.code == "content_protected"
        assert len(requests) == 1
        assert json.loads(requests[0].content) == {
            "site": site,
            "task_id": source.workspace.path.name.rsplit("-", 1)[0],
            "deadline": source.run_context.deadline.isoformat(),
        }
        assert len(calls) == 1
        assert list(root.iterdir()) == []
    finally:
        if result is not None:
            await close_material(result.run_context)
        source.workspace.cleanup()


@pytest.mark.parametrize(
    "reply,cause",
    [
        (
            {"cookies": "not base64!", "digest": "a" * 64},
            "identity_cookie_encoding_invalid",
        ),
        ({"cookies": [], "digest": "a" * 64}, "identity_material_invalid"),
        ({"cookies": "", "digest": "a" * 64}, "identity_cookie_payload_invalid"),
        ({"cookies": "", "digest": 123}, "identity_material_invalid"),
    ],
)
async def test_runner_material_field_and_encoding_errors_are_precise(
    transport, reply, cause
):
    root, _, state, _ = transport
    state.reply = reply
    with pytest.raises(LayerFailure) as caught:
        await identity.fetch_identity("instagram", "task", deadline())
    assert caught.value.failure.evidence["cause_code"] == cause
    assert list(root.iterdir()) == []
