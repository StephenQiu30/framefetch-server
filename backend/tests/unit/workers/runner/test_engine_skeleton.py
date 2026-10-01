"""P0 declarations, fail-closed seams and R0 execution equivalence."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path

import pytest
from app.services.provider_failures import FailureClass
from app.services.provider_types import EgressRoute, Layer, ProviderKey
from app.workers.runner.engine.egress import resolve_egress
from app.workers.runner.engine.identity import fetch_identity
from app.workers.runner.engine.ladder import run_ladder
from app.workers.runner.engine.layers.base import LayerFailure
from app.workers.runner.engine.layers.browser import BrowserLayer
from app.workers.runner.engine.layers.prepared import PreparedLayer
from app.workers.runner.engine.run_context import ResolutionSource, RunContext
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.metadata import MediaInspection
from app.workers.runner.provider_catalog_incremental import peertube_profile
from app.workers.runner.provider_registry import (
    ProviderRegistry,
    current_provider_registry,
    provider_request,
)
from app.workers.runner.service import MediaRunnerService
from app.workers.runner.workspace import WorkspaceLimits, WorkspaceManager
from helpers import download_request, settings

# Independently transcribed from Design 17 section 4.
_DECLARATIONS = {
    "bilibili": ("L1", "cn", "optional", "public"),
    "youtube": ("L2,L3", "global", "optional", "public"),
    "douyin": ("L3,L1", "cn", "optional", "public"),
    "tiktok": ("L1,L3", "global", "none", "public"),
    "xiaohongshu": ("L3,L1", "cn", "optional", "public"),
    "kuaishou": ("L2,L3", "cn", "optional", "public"),
    "weibo": ("L2,L3", "cn", "optional", "public"),
    "wechat_channels": ("L3", "cn", "required", "public"),
    "qqvideo": ("L1,L3", "cn", "required", "personal_full"),
    "youku": ("L1,L3", "cn", "required", "personal_full"),
    "hongguo_web": ("L1,L3", "cn", "optional", "public"),
    "x": ("L1,L3", "global", "optional", "public"),
    "instagram": ("L1,L3", "global", "required", "public"),
    "facebook": ("L1,L3", "global", "optional", "public"),
    "wechat_official_account_article": ("L1", "cn", "none", "public"),
}


@pytest.mark.parametrize("key", list(ProviderKey))
def test_all_platform_declarations(key):
    profile = (
        peertube_profile(frozenset({"video.example.org"}))
        if key is ProviderKey.PEERTUBE
        else current_provider_registry().profile_for_key(key)
    )
    ladder, route, identity, scope = _DECLARATIONS.get(
        key, ("L1", "global", "none", "public")
    )
    assert tuple(profile.ladder) == tuple(ladder.split(","))
    assert profile.egress_route == (
        EgressRoute.BY_DOMAIN if key is ProviderKey.GENERIC else f"{route}_residential"
    )
    assert profile.identity == identity and profile.content_scope == scope
    assert (profile.l2_prepare is not None) == (Layer.L2 in profile.ladder)
    assert (profile.l3_rules is not None) == (Layer.L3 in profile.ladder)


@pytest.mark.parametrize(
    "changes",
    [
        {"ladder": ()},
        {"ladder": (Layer.L1, Layer.L1)},
        {"ladder": (Layer.L2,)},
        {"ladder": (Layer.L3,)},
    ],
)
def test_registry_rejects_incomplete_engine_declarations(changes):
    profile = current_provider_registry().profile_for_key("bilibili")
    with pytest.raises(ValueError):
        ProviderRegistry((replace(profile, **changes),))


def test_article_path_boundary():
    registry = current_provider_registry()
    assert (
        registry.prepare("https://mp.weixin.qq.com/s/example").profile.key
        == "wechat_official_account_article"
    )
    with pytest.raises(RunnerFailure):
        registry.prepare("https://mp.weixin.qq.com/cgi-bin/home")


def test_egress_preserves_existing_proxy_override(tmp_path):
    config = settings(tmp_path)
    config.runner_provider_egress_proxies = {"bilibili": "http://proxy.example:3128"}
    binding = resolve_egress(
        current_provider_registry().profile_for_key("bilibili"), settings=config
    )
    assert binding.proxy_url == "http://proxy.example:3128"
    assert binding.route == "provider:bilibili"
    assert binding.egress_class == "unknown" and binding.observed_ip is None
    assert "proxy.example" not in repr(binding)


def source_for(service, tmp_path):
    request = provider_request("https://www.bilibili.com/video/BV13x41117TL")
    deadline = datetime.now(UTC) + timedelta(seconds=5)
    workspace = WorkspaceManager(tmp_path, WorkspaceLimits()).create("engine_sample")
    return ResolutionSource(
        request,
        workspace,
        service._inspection,
        service._context(request),
        RunContext(
            resolve_egress(request.profile, settings=settings(tmp_path)),
            "",
            "",
            None,
            None,
            None,
            deadline,
        ),
    )


async def test_l1_preserves_retry_facts(tmp_path, monkeypatch):
    service = MediaRunnerService(settings(tmp_path))
    source = source_for(service, tmp_path)
    media = MediaInspection(
        "work-id",
        "Title",
        30,
        "Youtube",
        (),
        thumbnail_urls=("https://media.example/a",),
    )
    calls = 0

    async def inspect(request, workspace, *, context, cookie_jar):
        nonlocal calls
        calls += 1
        assert request == source.request and cookie_jar is None
        assert context.resolved_layer == "L1" and not context.identity_used
        if calls == 1:
            raise RunnerFailure("network_transient", status=503)
        return media

    monkeypatch.setattr(service._inspection, "inspect", inspect)
    result = await run_ladder(
        source, source.request.profile, source.run_context.deadline
    )
    assert calls == 2
    assert result.media.provider_media_id == media.provider_media_id
    assert result.media.thumbnail_urls == media.thumbnail_urls
    assert result.media.streams is media.streams
    assert result.media.handoff == "http" and result.media.client == "yt-dlp-default"
    assert result.execution_context == source.execution_context
    assert [f.code for f in result.failures] == ["network_transient"]
    with pytest.raises(FrozenInstanceError):
        source.run_context.deadline = datetime.now(UTC)
    source.workspace.cleanup()


@pytest.mark.parametrize("operation", ["inspect", "download"])
async def test_both_runner_operations_enter_run_ladder(
    tmp_path, monkeypatch, operation
):
    service = MediaRunnerService(settings(tmp_path))
    calls = []

    async def resolve(source, profile, deadline):
        calls.append((source, profile, deadline))
        raise RunnerFailure("network_blocked")

    monkeypatch.setattr("app.workers.runner.service.run_ladder", resolve)
    with pytest.raises(RunnerFailure, match="network blocked"):
        if operation == "inspect":
            await service.inspect("https://media.example.com/video")
        else:
            await service.download(download_request())
    assert len(calls) == 1 and calls[0][0].execution_context.resolved_layer == "L1"
    assert list(tmp_path.iterdir()) == []


async def test_expired_identity_request_fails_closed():
    with pytest.raises(LayerFailure) as caught:
        await fetch_identity("instagram", "task", datetime.now(UTC))
    assert caught.value.failure.failure_class is FailureClass.IDENTITY_UNAVAILABLE


@pytest.mark.parametrize("layer", [PreparedLayer(), BrowserLayer()])
async def test_layer_stubs_fail_closed(layer, tmp_path):
    source = source_for(MediaRunnerService(settings(tmp_path)), tmp_path)
    with pytest.raises(LayerFailure) as caught:
        await layer.resolve(source, source.run_context)
    assert caught.value.failure.failure_class is FailureClass.RUNTIME_UNAVAILABLE
    source.workspace.cleanup()


@pytest.mark.parametrize("key", [k for k, v in _DECLARATIONS.items() if "L3" in v[0]])
def test_platform_parser_seams_fail_closed(key):
    module = import_module(f"app.workers.runner.engine.browser.{key}")
    assert module.RULES.platform == key
    with pytest.raises(LayerFailure):
        module.parse_response({})


def test_layer_failure_rejects_raw_evidence():
    with pytest.raises(ValueError, match="unsupported facts"):
        LayerFailure(
            FailureClass.CHALLENGE, "②", {"kind": "runtime", "stderr": "secret"}
        )


def test_matrix_uses_no_runner_imports():
    import ast
    import json

    root = Path(__file__).resolve().parents[4]
    tree = ast.parse((root / "scripts/coldstart_matrix.py").read_text())
    assert not any(
        isinstance(node, ast.ImportFrom) and node.module and "app" in node.module
        for node in ast.walk(tree)
    )
    cases = json.loads((root / "scripts/fixtures/coldstart_cases.json").read_text())
    assert cases and all("platform" in case for case in cases)


async def test_expired_ladder_deadline_does_not_start_platform_io(
    tmp_path, monkeypatch
):
    service = MediaRunnerService(settings(tmp_path))
    source = source_for(service, tmp_path)

    async def unexpected(*args, **kwargs):
        pytest.fail("expired ladder reached platform I/O")

    monkeypatch.setattr(service._inspection, "inspect", unexpected)
    with pytest.raises(RunnerFailure, match="inspection timeout"):
        await run_ladder(source, source.request.profile, datetime.now(UTC))
    source.workspace.cleanup()
