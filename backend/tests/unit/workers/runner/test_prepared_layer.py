"""Client aggregation and bounded first-party visitor preparation."""

import asyncio
from dataclasses import replace

import httpx
import pytest
from app.services.provider_failures import FailureClass
from app.workers.runner.engine import identity
from app.workers.runner.engine.ladder import close_material, run_ladder
from app.workers.runner.engine.layers.base import LayerFailure
from app.workers.runner.engine.layers.http import HttpLayer
from app.workers.runner.engine.layers.prepared import PreparedLayer, prepare_visitor
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import provider_request
from app.workers.runner.service import MediaRunnerService
from helpers import settings
from test_engine_skeleton import source_for
from test_p1_wiring import resolved


@pytest.fixture
def source(tmp_path):
    service = MediaRunnerService(settings(tmp_path))
    original = source_for(service, tmp_path)
    request = provider_request("https://www.youtube.com/watch?v=jNQXAC9IVRw")
    item = replace(
        original, request=request, execution_context=service._context(request)
    )
    yield item
    item.workspace.cleanup()


@pytest.mark.parametrize(
    "outcomes,expected",
    [
        (
            [FailureClass.CONTENT_PROTECTED, FailureClass.CONTENT_PROTECTED, None],
            "youtube:default",
        ),
        ([FailureClass.FORMAT_UNAVAILABLE, None], "youtube:tv"),
        ([None], "youtube:mweb"),
    ],
)
async def test_clients_record_actual_success_and_attempts(
    source, monkeypatch, outcomes, expected
):
    calls = []

    async def resolve(self, item, ctx):
        calls.append(item.execution_context.client)
        outcome = outcomes.pop(0)
        if outcome:
            raise LayerFailure(outcome, "②", {"kind": "unknown"})
        return resolved(ctx, client=item.execution_context.client)

    monkeypatch.setattr(HttpLayer, "resolve", resolve)
    result = await run_ladder(
        source, source.request.profile, source.run_context.deadline
    )
    assert result.execution_context.client == expected
    assert calls == ["youtube:mweb", "youtube:tv", "youtube:default"][: len(calls)]
    assert result.failures[0].failure_class is FailureClass.IDENTITY_UNAVAILABLE
    assert len(result.failures) == len(calls)


@pytest.mark.parametrize(
    "outcomes,expected",
    [
        ([FailureClass.CONTENT_PROTECTED] * 3, FailureClass.CONTENT_PROTECTED),
        (
            [
                FailureClass.CONTENT_PROTECTED,
                FailureClass.FORMAT_UNAVAILABLE,
                FailureClass.CONTENT_PROTECTED,
            ],
            FailureClass.FORMAT_UNAVAILABLE,
        ),
        (
            [
                FailureClass.CONTENT_PROTECTED,
                FailureClass.NETWORK_BLOCKED,
                FailureClass.CONTENT_PROTECTED,
            ],
            FailureClass.NETWORK_BLOCKED,
        ),
        (
            [
                FailureClass.CONTENT_PROTECTED,
                FailureClass.EXTRACTOR_BROKEN,
                FailureClass.FORMAT_UNAVAILABLE,
            ],
            FailureClass.EXTRACTOR_BROKEN,
        ),
        (
            [
                FailureClass.NETWORK_BLOCKED,
                FailureClass.CHALLENGE,
                FailureClass.FORMAT_UNAVAILABLE,
            ],
            FailureClass.CHALLENGE,
        ),
    ],
)
async def test_protected_requires_every_client_to_prove_drm(
    source, monkeypatch, outcomes, expected, caplog
):
    caplog.set_level("WARNING", logger="app.workers.runner.engine.layers.prepared")

    async def resolve(self, item, ctx):
        raise LayerFailure(outcomes.pop(0), "②", {"kind": "unknown"})

    monkeypatch.setattr(HttpLayer, "resolve", resolve)
    with pytest.raises(RunnerFailure) as caught:
        await PreparedLayer().resolve(source, source.run_context)
    assert caught.value.failure.failure_class is expected
    assert len(caught.value.failures) == 3
    assert caplog.text.count("proof client failed task=") == 3


@pytest.mark.parametrize(
    "kind",
    [
        FailureClass.LOGIN_REQUIRED,
        FailureClass.RATE_LIMITED,
        FailureClass.RUNTIME_UNAVAILABLE,
        FailureClass.TRANSIENT,
        FailureClass.CONTENT_UNAVAILABLE,
    ],
)
async def test_client_chain_leaves_recovery_to_ladder(source, monkeypatch, kind):
    calls = []

    async def resolve(self, item, ctx):
        calls.append(item.execution_context.client)
        raise LayerFailure(kind, "none", {"kind": "unknown"})

    monkeypatch.setattr(HttpLayer, "resolve", resolve)
    with pytest.raises(RunnerFailure) as caught:
        await PreparedLayer().resolve(source, source.run_context)
    assert caught.value.failure.failure_class is kind and calls == ["youtube:mweb"]


async def test_download_uses_confirmed_client_without_fallback(source, monkeypatch):
    expected = replace(source.execution_context, client="youtube:tv")
    source = replace(source, expected_context=expected)
    calls = []

    async def resolve(self, item, ctx):
        calls.append(item.execution_context.client)
        raise LayerFailure(FailureClass.FORMAT_UNAVAILABLE, "none", {"kind": "unknown"})

    monkeypatch.setattr(HttpLayer, "resolve", resolve)
    with pytest.raises(RunnerFailure):
        await PreparedLayer().resolve(source, source.run_context)
    assert calls == ["youtube:tv"]


@pytest.fixture
def guest_runtime(tmp_path, monkeypatch):
    root = tmp_path / "identity"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(identity, "COOKIE_TMPFS_ROOT", root)
    monkeypatch.setattr(identity, "_on_tmpfs", lambda path: True)
    original = httpx.AsyncClient
    observed = []

    def install(handler):
        def client(**kwargs):
            observed.append(kwargs.pop("proxy"))
            assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
            return original(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(
            "app.workers.runner.engine.layers.prepared.httpx.AsyncClient", client
        )

    return root, observed, install


@pytest.mark.parametrize("site", ["kuaishou", "weibo"])
async def test_first_party_sequence_and_guest_cookie_handoff(
    source, guest_runtime, site
):
    root, proxies, install = guest_runtime
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/visitor/genvisitor":
            assert request.method == "POST" and b"gen_callback" in request.content
            return httpx.Response(
                200,
                content=b'gen_callback({"data":{"tid":"guest","confidence":80,"new_tid":true}});',
            )
        if request.url.path == "/visitor/visitor":
            assert (
                request.url.params["a"] == "incarnate"
                and request.url.params["t"] == "guest"
            )
            assert request.url.params["c"] == "080"
        return httpx.Response(
            200,
            headers={
                "Set-Cookie": f"visitor=ephemeral; Domain=.{site}.com; Path=/; Secure"
            },
        )

    install(handler)
    ctx = await prepare_visitor(site, source.run_context)
    assert [request.url.path for request in requests] == (
        ["/"]
        if site == "kuaishou"
        else ["/", "/visitor/genvisitor", "/visitor/visitor", "/"]
    )
    assert all(request.headers["User-Agent"] == ctx.user_agent for request in requests)
    assert proxies == [source.run_context.egress.proxy_url]
    assert (
        ctx.identity is None and ctx.cookie_file.parent.stat().st_mode & 0o777 == 0o700
    )
    assert ctx.cookie_file.stat().st_mode & 0o777 == 0o600
    assert "ephemeral" in ctx.cookie_file.read_text() and "ephemeral" not in repr(ctx)
    await close_material(ctx)
    assert list(root.iterdir()) == []


@pytest.mark.parametrize(
    "status,expected",
    [
        (429, FailureClass.RATE_LIMITED),
        (403, FailureClass.CHALLENGE),
        (503, FailureClass.TRANSIENT),
    ],
)
async def test_guest_status_and_retry_after(source, guest_runtime, status, expected):
    root, _, install = guest_runtime
    install(lambda request: httpx.Response(status, headers={"Retry-After": "15"}))
    with pytest.raises(LayerFailure) as caught:
        await prepare_visitor("weibo", source.run_context)
    assert caught.value.failure.failure_class is expected
    if status == 429:
        assert caught.value.status == 429
        assert caught.value.failure.retry_after is not None
        assert caught.value.failure.evidence == {
            "kind": "upstream_response",
            "http_status": 429,
        }
    assert list(root.iterdir()) == []


@pytest.mark.parametrize(
    "body", [b"{}", b'gen_callback({"data":{"tid":23}});', b"not-json", b"[]"]
)
async def test_guest_invalid_structure_is_safe(source, guest_runtime, body):
    root, _, install = guest_runtime
    install(lambda request: httpx.Response(200, content=body))
    with pytest.raises(LayerFailure) as caught:
        await prepare_visitor("weibo", source.run_context)
    assert caught.value.failure.evidence["cause_code"] == "visitor_structure_changed"
    assert list(root.iterdir()) == []


@pytest.mark.parametrize(
    "location",
    [
        "http://127.0.0.1/",
        "https://other.example/",
        "https://weibo.com:8443/",
        "https://user:secret@weibo.com/",
    ],
)
async def test_redirect_scope(source, guest_runtime, location):
    root, _, install = guest_runtime
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": location})

    install(handler)
    with pytest.raises(LayerFailure) as caught:
        await prepare_visitor("weibo", source.run_context)
    assert caught.value.failure.failure_class is FailureClass.INVALID_INPUT
    assert len(calls) == 1 and list(root.iterdir()) == []


async def test_response_size_bound(source, guest_runtime):
    root, _, install = guest_runtime
    install(lambda request: httpx.Response(200, content=b"x" * (1024 * 1024 + 1)))
    with pytest.raises(LayerFailure) as caught:
        await prepare_visitor("kuaishou", source.run_context)
    assert caught.value.failure.evidence["cause_code"] == "visitor_response_too_large"
    assert list(root.iterdir()) == []


async def test_cancel_removes_visitor_material(source, guest_runtime, monkeypatch):
    root, _, install = guest_runtime
    install(
        lambda request: httpx.Response(
            200, headers={"Set-Cookie": "did=guest; Domain=.kuaishou.com; Path=/"}
        )
    )
    source = replace(
        source, request=provider_request("https://www.kuaishou.com/short-video/sample")
    )

    async def cancelled(self, item, ctx):
        assert ctx.cookie_file.exists()
        raise asyncio.CancelledError

    monkeypatch.setattr(HttpLayer, "resolve", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await PreparedLayer().resolve(source, source.run_context)
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("client", ["youtube:mweb", "youtube:tv", "youtube:default"])
def test_command_client_override_retains_only_one_client_and_bgutil(tmp_path, client):
    from app.workers.runner.yt_dlp_commands import YtDlpCommandBuilder
    from helpers import run_context

    config = settings(tmp_path).model_copy(
        update={"runner_youtube_pot_base_url": "http://pot:4416"}
    )
    command = YtDlpCommandBuilder(
        config, tmp_path, run_context(config), client=client
    ).inspect("https://youtu.be/jNQXAC9IVRw", cookie_jar=None)
    assert [
        value for value in command.argv if value.startswith("youtube:player_client=")
    ] == [f"youtube:player_client={client.split(':')[1]}"]
    assert "youtubepot-bgutilhttp:base_url=http://pot:4416" in command.argv
