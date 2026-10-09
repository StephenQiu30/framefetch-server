"""P1 seams exercised with layers and browser handles, without live providers."""

import asyncio
from dataclasses import fields, replace
from pathlib import Path

import httpx
import pytest
from app.services.provider_failures import FailureClass
from app.services.provider_types import Layer, ProviderIdentity
from app.workers.runner.commands import MediaCommands
from app.workers.runner.contracts import ExecutionContextContract
from app.workers.runner.engine import identity
from app.workers.runner.engine.egress import EgressBinding
from app.workers.runner.engine.ladder import LAYER_TABLE, run_ladder
from app.workers.runner.engine.layers.base import LayerFailure
from app.workers.runner.engine.resolved import ResolvedMedia
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.service import MediaRunnerService
from app.workers.runner.utilities import normalize_for_settings
from app.workers.runner.version import engine_revision
from app.workers.runner.yt_dlp_commands import YtDlpCommandBuilder
from helpers import download_request, run_context, settings, split_media_info
from test_commands import RecordingSupervisor
from test_engine_skeleton import source_for
from test_service import FixtureSupervisor


def resolved(ctx, *, client="stub:actual", browser=False):
    payload = split_media_info()
    for raw in payload["formats"]:
        raw["url"] = f"https://media.example.com/{raw['format_id']}"
    inspection = normalize_for_settings(payload, settings(Path("/tmp/p1-fixture")))
    return ResolvedMedia(
        **{field.name: getattr(inspection, field.name) for field in fields(inspection)},
        client=client,
        handoff="browser" if browser else "http",
        run_context=ctx,
    )


@pytest.mark.parametrize(
    "failure",
    [
        FailureClass.NETWORK_BLOCKED,
        FailureClass.CHALLENGE,
        FailureClass.EXTRACTOR_BROKEN,
        FailureClass.FORMAT_UNAVAILABLE,
    ],
)
async def test_declared_order_advances_only_on_p1_failures(
    tmp_path, monkeypatch, failure
):
    service = MediaRunnerService(settings(tmp_path))
    source = source_for(service, tmp_path)
    profile = replace(source.request.profile, ladder=(Layer.L1, Layer.L2, Layer.L3))
    source = replace(source, request=replace(source.request, profile=profile))
    calls = []

    class Failed:
        async def resolve(self, source, ctx):
            calls.append(source.execution_context.resolved_layer)
            raise LayerFailure(failure, "②", {"kind": "unknown"})

    class Success:
        async def resolve(self, source, ctx):
            calls.append(source.execution_context.resolved_layer)
            return resolved(ctx)

    monkeypatch.setitem(LAYER_TABLE, Layer.L1, Failed)
    monkeypatch.setitem(LAYER_TABLE, Layer.L2, Failed)
    monkeypatch.setitem(LAYER_TABLE, Layer.L3, Success)
    try:
        result = await run_ladder(source, profile, source.run_context.deadline)
        assert calls == ["L1", "L2", "L3"]
        assert result.execution_context.resolved_layer == "L3"
        assert result.execution_context.client == "stub:actual"
        assert [error.layer for error in result.failures] == ["L1", "L1", "L2"]
        assert result.failures[0].failure_class is FailureClass.IDENTITY_UNAVAILABLE
    finally:
        source.workspace.cleanup()


@pytest.mark.parametrize(
    "kind",
    [
        FailureClass.CONTENT_PROTECTED,
        FailureClass.CONTENT_UNAVAILABLE,
        FailureClass.LOGIN_REQUIRED,
        FailureClass.IDENTITY_UNAVAILABLE,
        FailureClass.INVALID_INPUT,
    ],
)
async def test_terminal_failure_never_dispatches_next_layer(
    tmp_path, monkeypatch, kind
):
    service = MediaRunnerService(settings(tmp_path))
    source = source_for(service, tmp_path)
    profile = replace(
        source.request.profile,
        ladder=(Layer.L1, Layer.L2),
        identity=ProviderIdentity.NONE,
    )
    source = replace(source, request=replace(source.request, profile=profile))

    class Failed:
        async def resolve(self, source, ctx):
            raise LayerFailure(kind, "none", {"kind": "unknown"})

    class Unexpected:
        def __init__(self):
            pytest.fail("terminal failure advanced the ladder")

    monkeypatch.setitem(LAYER_TABLE, Layer.L1, Failed)
    monkeypatch.setitem(LAYER_TABLE, Layer.L2, Unexpected)
    try:
        with pytest.raises(RunnerFailure) as caught:
            await run_ladder(source, profile, source.run_context.deadline)
        assert caught.value.failure.failure_class is kind
    finally:
        source.workspace.cleanup()


class Browser:
    user_agent = "stub browser"

    def __init__(self, *, fail=False, block=False):
        self.events = []
        self.started = asyncio.Event()
        self.fail = fail
        self.block = block

    async def cookies(self):
        return []

    async def download(self, url, dest):
        self.events.append(("start", url))
        self.started.set()
        if self.block:
            await asyncio.Event().wait()
        if self.fail:
            raise RunnerFailure("network_blocked")
        dest.write_bytes(b"browser media")
        self.events.append(("saved", dest.name))

    async def close(self):
        self.events.append(("close", None))


@pytest.mark.parametrize("outcome", ["success", "fail", "cancel", "context_changed"])
async def test_browser_handoff_retains_handle_until_transfer_completes(
    tmp_path, monkeypatch, outcome
):
    browser = Browser(fail=outcome == "fail", block=outcome == "cancel")
    service = MediaRunnerService(
        settings(tmp_path), supervisor=FixtureSupervisor(split_media_info())
    )
    from app.workers.runner.provider_registry import provider_request

    url = "https://www.tiktok.com/@fixture/video/123"
    request = download_request()
    request.url = url
    expected = replace(
        service._context(provider_request(url)),
        resolved_layer="L3",
        client="stub:actual",
        browser_context_kind="anonymous",
    )
    request.execution_context = ExecutionContextContract.from_domain(expected)

    class Success:
        async def resolve(self, source, ctx):
            material = ctx.with_material(browser=browser, user_agent=browser.user_agent)
            media = resolved(
                material,
                client="stub:changed"
                if outcome == "context_changed"
                else "stub:actual",
                browser=True,
            )
            media.download_info["http_headers"] = {
                "X-Session-Token": "fixture-header-value"
            }
            for raw in media.download_info["formats"]:
                raw["url"] += "?signature=fixture-signature-value"
            return media

    monkeypatch.setitem(LAYER_TABLE, Layer.L3, Success)

    async def unexpected(*args, **kwargs):
        pytest.fail("browser handoff used yt-dlp transfer")

    monkeypatch.setattr(service._commands, "download_stream", unexpected)

    def unexpected_info(*args, **kwargs):
        pytest.fail("browser handoff persisted resolution metadata")

    monkeypatch.setattr(
        "app.workers.runner.service.write_resolved_info", unexpected_info
    )
    task = asyncio.create_task(service.download(request))
    if outcome == "cancel":
        await browser.started.wait()
        assert not any(event[0] == "close" for event in browser.events)
        task.cancel()
    if outcome == "success":
        result = await task
        assert result.artifact.size_bytes > 0
        assert [event[0] for event in browser.events] == [
            "start",
            "saved",
            "start",
            "saved",
            "close",
        ]
        assert [event[1] for event in browser.events if event[0] == "start"] == [
            "https://media.example.com/video?signature=fixture-signature-value",
            "https://media.example.com/audio?signature=fixture-signature-value",
        ]
        workspace = Path(result.workspace_path)
        assert not (workspace / "resolved.info.json").exists()
        for path in workspace.rglob("*"):
            if path.is_file():
                content = path.read_bytes()
                assert b"fixture-signature-value" not in content
                assert b"fixture-header-value" not in content
        from shutil import rmtree

        rmtree(result.workspace_path)
    else:
        with pytest.raises(RunnerFailure):
            await task
        assert browser.events[-1] == ("close", None)
        if outcome == "context_changed":
            assert browser.events == [("close", None)]
        assert list(tmp_path.iterdir()) == []


def test_cookie_command_accepts_only_private_tmpfs(tmp_path, monkeypatch):
    root = tmp_path / "identity"
    operation = root / "operation"
    operation.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    cookie = operation / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n")
    cookie.chmod(0o600)
    monkeypatch.setattr(identity, "COOKIE_TMPFS_ROOT", root)
    monkeypatch.setattr(identity, "_on_tmpfs", lambda path: True)
    ctx = run_context(settings(tmp_path)).with_material(cookie_file=cookie)
    command = YtDlpCommandBuilder(settings(tmp_path), tmp_path, ctx).inspect(
        "https://media.example.com/video", cookie_jar=cookie
    )
    assert command.argv[command.argv.index("--cookies") + 1] == str(cookie)
    assert not command.authenticated  # A guest Cookie file is not account identity.
    for path in [tmp_path / "outside", operation / "symlink", root / "cookies.txt"]:
        if path.name == "symlink":
            path.symlink_to(cookie)
        with pytest.raises(RunnerFailure):
            identity.validate_cookie_file(path)
    cookie.chmod(0o644)
    with pytest.raises(RunnerFailure):
        identity.validate_cookie_file(cookie)
    cookie.chmod(0o600)
    monkeypatch.setattr(identity, "_on_tmpfs", lambda path: False)
    with pytest.raises(RunnerFailure):
        identity.validate_cookie_file(cookie)


async def test_network_commands_use_injected_binding_despite_settings(
    tmp_path, monkeypatch
):
    config = settings(tmp_path)
    injected = EgressBinding(
        "injected", "http://binding-only:3128", "revision", "residential", "203.0.113.7"
    )
    ctx = replace(run_context(config), egress=injected)
    supervisor = RecordingSupervisor()
    commands = MediaCommands(config, supervisor).with_context(ctx)
    await commands.inspect("https://media.example.com/video", tmp_path)
    assert supervisor.argv[supervisor.argv.index("--proxy") + 1] == injected.proxy_url
    assert supervisor.env["HTTPS_PROXY"] == injected.proxy_url
    await commands.probe_remote("https://media.example.com/video", tmp_path)
    assert supervisor.env["http_proxy"] == injected.proxy_url
    observed = []
    original = httpx.AsyncClient

    def client(**kwargs):
        observed.append(kwargs.pop("proxy"))
        return original(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"image")
            ),
            **kwargs,
        )

    monkeypatch.setattr("app.workers.runner.commands.httpx.AsyncClient", client)
    await commands.probe_remote_prefix(
        "https://media.example.com/video",
        tmp_path,
        referer="https://media.example.com/video",
    )
    await commands.download_public_asset(
        "https://media.example.com/image",
        tmp_path / "image",
        tmp_path,
        referer="https://media.example.com/video",
        max_bytes=100,
    )
    assert observed == [injected.proxy_url, injected.proxy_url]
    assert "binding-only" not in repr(ctx)


def test_engine_revision_covers_packages_plugins_and_browser(tmp_path, monkeypatch):
    import importlib.metadata

    from app.workers.runner import browser_runtime

    config = settings(tmp_path)
    first = engine_revision(config)
    assert first == engine_revision() and len(first) == 64
    monkeypatch.setattr(
        importlib.metadata,
        "version",
        lambda package: "changed" if package == "yt-dlp-ejs" else "fixture",
    )
    second = engine_revision(config)
    assert second != first
    monkeypatch.setattr(browser_runtime, "CHROMIUM_VERSION", "next-browser")
    assert engine_revision(config) != second


async def test_inspection_thumbnail_uses_actual_binding(tmp_path, monkeypatch):
    service = MediaRunnerService(settings(tmp_path))
    injected = EgressBinding(
        "actual", "http://actual-binding:3128", "revision", "residential", None
    )
    seen = []

    class Success:
        async def resolve(self, source, ctx):
            return resolved(replace(ctx, egress=injected))

    async def thumbnail(urls, *, referer, egress_proxy):
        seen.append(egress_proxy)
        return None

    monkeypatch.setitem(LAYER_TABLE, Layer.L1, Success)
    monkeypatch.setattr(service._thumbnails, "fetch", thumbnail)
    response = await service.inspect("https://www.bilibili.com/video/BV13x41117TL")
    assert seen == [injected.proxy_url]
    assert response.execution_context.egress_route == injected.route


def test_public_context_is_read_only_and_has_exactly_twelve_fields():
    from app.core.config import Settings
    from app.main import create_app

    schema = create_app(Settings(app_env="test")).openapi()["components"]["schemas"]
    for name in ("InspectionResponse", "DownloadResponse"):
        context = schema[name]["properties"]["execution_context"]
        assert context["readOnly"] is True
        assert {"$ref": "#/components/schemas/ExecutionContext"} in context["anyOf"]
    assert set(schema["ExecutionContext"]["properties"]) == {
        "provider_key",
        "registry_revision",
        "resolved_layer",
        "client",
        "engine_revision",
        "egress_route",
        "egress_revision",
        "egress_class",
        "egress_observed_ip",
        "identity_used",
        "identity_digest",
        "browser_context_kind",
    }


async def test_download_rejects_rotated_semantic_dimensions_before_transfer(
    tmp_path, monkeypatch
):
    service = MediaRunnerService(
        settings(tmp_path), supervisor=FixtureSupervisor(split_media_info())
    )

    class Success:
        async def resolve(self, source, ctx):
            media = resolved(ctx, client=source.execution_context.client)
            # The old selector accepts a nearby rendition; P1 requires reconfirmation.
            streams = tuple(
                replace(stream, width=1800, height=1012)
                if stream.kind.value == "video"
                else stream
                for stream in media.streams
            )
            return replace(media, streams=streams)

    monkeypatch.setitem(LAYER_TABLE, Layer.L1, Success)
    with pytest.raises(RunnerFailure) as caught:
        await service.download(download_request())
    assert caught.value.failure.failure_class is FailureClass.CONTEXT_CHANGED
    assert list(tmp_path.iterdir()) == []


async def test_inspection_cleans_workspace_even_if_browser_close_fails(
    tmp_path, monkeypatch
):
    service = MediaRunnerService(settings(tmp_path))

    class BrokenBrowser(Browser):
        async def close(self):
            raise RuntimeError("browser close failed")

    class Success:
        async def resolve(self, source, ctx):
            return resolved(ctx.with_material(browser=BrokenBrowser()))

    monkeypatch.setitem(LAYER_TABLE, Layer.L3, Success)
    with pytest.raises(RuntimeError, match="browser close failed"):
        await service.inspect("https://www.douyin.com/video/123")
    assert list(tmp_path.iterdir()) == []


async def test_download_missing_identity_changes_context_before_layer_io(
    tmp_path, monkeypatch
):
    service = MediaRunnerService(settings(tmp_path))
    source = source_for(service, tmp_path)
    expected = replace(
        source.execution_context,
        identity_used=True,
        identity_digest="previous-material",
    )
    source = replace(source, expected_context=expected)

    class Unexpected:
        async def resolve(self, source, ctx):
            pytest.fail("download silently switched to anonymous identity")

    monkeypatch.setitem(LAYER_TABLE, Layer.L1, Unexpected)
    try:
        with pytest.raises(RunnerFailure) as caught:
            await run_ladder(
                source, source.request.profile, source.run_context.deadline
            )
        assert caught.value.failure.failure_class is FailureClass.CONTEXT_CHANGED
    finally:
        source.workspace.cleanup()


@pytest.mark.parametrize("filename", ["metadata.py", "verification.py", "options.py"])
def test_engine_revision_invalidates_plans_after_selection_policy_change(
    tmp_path, monkeypatch, filename
):
    from pathlib import Path

    from app.workers.runner import version

    read_bytes = Path.read_bytes
    before = engine_revision(settings(tmp_path))

    def changed(path):
        data = read_bytes(path)
        return (
            data + b"\n# changed policy\n"
            if path.name == filename and path.parent == Path(version.__file__).parent
            else data
        )

    monkeypatch.setattr(Path, "read_bytes", changed)
    assert engine_revision(settings(tmp_path)) != before


@pytest.mark.parametrize("filename", ["formats.py", "enums.py", "selection.py"])
def test_engine_revision_invalidates_shared_download_rules(
    tmp_path, monkeypatch, filename
):
    from pathlib import Path

    from app.workers.runner import version

    rule_root = (
        Path(version.__file__).parent.parent.parent / "services" / "downloads" / "rules"
    )
    read_bytes = Path.read_bytes
    before = engine_revision(settings(tmp_path))

    def changed(path):
        data = read_bytes(path)
        return (
            data + b"\n# changed shared rule\n"
            if path == rule_root / filename
            else data
        )

    monkeypatch.setattr(Path, "read_bytes", changed)
    assert engine_revision(settings(tmp_path)) != before
