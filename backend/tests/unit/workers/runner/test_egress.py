from dataclasses import fields, replace

import httpx
import pytest
from app.workers.runner.engine import egress
from app.workers.runner.provider_registry import (
    current_provider_registry,
    provider_request,
)
from app.workers.runner.service import MediaRunnerService
from app.workers.runner.settings import ProviderEgressSettings


@pytest.fixture
def config():
    return ProviderEgressSettings(
        runner_egress_proxy="http://egress-proxy:3128",
        runner_global_egress_proxy="http://egress-proxy:3129",
    )


def binding(config, key="youtube"):
    return egress.resolve_egress(
        current_provider_registry().profile_for_key(key), settings=config
    )


def test_routes_and_global_fallback(config):
    cn, global_ = binding(config, "bilibili"), binding(config)
    assert (cn.route, cn.proxy_url, cn.egress_class) == (
        "cn_residential",
        "http://egress-proxy:3128",
        "residential",
    )
    assert (global_.route, global_.proxy_url, global_.egress_class) == (
        "global_residential",
        "http://egress-proxy:3129",
        "datacenter",
    )
    config.egress_global_upstream_host = "host.docker.internal"
    residential = binding(config)
    assert residential.egress_class == "residential"
    assert residential.revision != global_.revision
    assert "host.docker.internal" not in repr(residential)


@pytest.mark.parametrize(
    "field,value",
    [
        ("egress_fallback_upstream_host", "another-host"),
        ("egress_fallback_upstream_port", 7899),
        ("egress_node_revision", "2"),
        ("runner_global_egress_proxy", "http://proxy:3130"),
    ],
)
def test_revision_tracks_effective_route_configuration(config, field, value):
    before = binding(config)
    setattr(config, field, value)
    assert binding(config).revision != before.revision
    assert binding(config).revision == binding(config).revision


def test_unused_fallback_does_not_change_residential_revision(config):
    config.egress_global_upstream_host = "residential-listener"
    before = binding(config)
    config.egress_fallback_upstream_port = 7999
    assert binding(config).revision == before.revision


def test_generic_route_uses_domain(tmp_path):
    from helpers import settings

    service = MediaRunnerService(settings(tmp_path))
    assert (
        service._context(
            provider_request("https://media.example.cn/a.mp4")
        ).egress_route
        == "cn_residential"
    )
    assert (
        service._context(
            provider_request("https://media.example.com/a.mp4")
        ).egress_route
        == "global_residential"
    )


@pytest.fixture
def clock_and_cache(monkeypatch):
    egress._observations.clear()
    now = [1000.0]
    monkeypatch.setattr(egress.time, "monotonic", lambda: now[0])
    yield now
    egress._observations.clear()


@pytest.mark.parametrize(
    "body,expected",
    [
        (b"8.8.8.8\n", "8.8.8.8"),
        (b"2606:4700:4700::1111", "2606:4700:4700::1111"),
        (b"127.0.0.1", None),
        (b"224.0.0.1", None),
        (b"ff02::1", None),
        (b"2606:4700:4700::1111%eth0", None),
        (b"garbage", None),
        (b"x" * 129, None),
    ],
)
async def test_observation_uses_binding_proxy_and_caches_ten_minutes(
    config, clock_and_cache, monkeypatch, body, expected
):
    real_client = httpx.AsyncClient
    calls = []

    def client(**kwargs):
        calls.append(kwargs)
        assert kwargs.pop("proxy") == "http://egress-proxy:3129"
        return real_client(
            **kwargs,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=body)
            ),
        )

    monkeypatch.setattr(egress.httpx, "AsyncClient", client)
    observed = await egress.observe_egress(binding(config), settings=config)
    assert observed.observed_ip == expected
    assert binding(config).observed_ip == expected
    clock_and_cache[0] += 599
    assert await egress.observe_egress(binding(config), settings=config) == observed
    assert len(calls) == 1
    clock_and_cache[0] += 1
    await egress.observe_egress(binding(config), settings=config)
    assert len(calls) == 2
    assert all(not call["trust_env"] and not call["follow_redirects"] for call in calls)


@pytest.mark.parametrize("mode", ["timeout", "redirect", "http_error"])
async def test_observation_failure_is_empty_and_cached(
    config, clock_and_cache, monkeypatch, mode
):
    real_client = httpx.AsyncClient
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        if mode == "timeout":
            raise httpx.ReadTimeout("timeout")
        return httpx.Response(
            302 if mode == "redirect" else 503,
            headers={"Location": "https://other.example"},
        )

    monkeypatch.setattr(
        egress.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handler),
            follow_redirects=kwargs["follow_redirects"],
        ),
    )
    assert (
        await egress.observe_egress(binding(config), settings=config)
    ).observed_ip is None
    assert (
        await egress.observe_egress(binding(config), settings=config)
    ).observed_ip is None
    assert count == 1


async def test_changed_revision_reobserves(config, clock_and_cache, monkeypatch):
    real_client = httpx.AsyncClient
    proxies = []

    def client(**kwargs):
        proxies.append(kwargs.pop("proxy"))
        return real_client(
            **kwargs,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"8.8.8.8")
            ),
        )

    monkeypatch.setattr(egress.httpx, "AsyncClient", client)
    await egress.observe_egress(binding(config), settings=config)
    config.egress_node_revision = "2"
    await egress.observe_egress(binding(config), settings=config)
    await egress.observe_egress(binding(config, "bilibili"), settings=config)
    assert proxies == [
        "http://egress-proxy:3129",
        "http://egress-proxy:3129",
        "http://egress-proxy:3128",
    ]


async def test_cancelled_observation_propagates(config, monkeypatch):
    import asyncio

    real_client = httpx.AsyncClient

    def handler(request):
        raise asyncio.CancelledError

    monkeypatch.setattr(
        egress.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler)),
    )
    egress._observations.clear()
    with pytest.raises(asyncio.CancelledError):
        await egress.observe_egress(binding(config), settings=config)
    assert not egress._observations


async def test_youtube_failure_diagnostic_includes_observed_binding(
    tmp_path, monkeypatch
):
    from app.workers.runner.errors import RunnerFailure
    from helpers import settings

    async def observed(binding, *, settings):
        return replace(binding, observed_ip="8.8.8.8")

    monkeypatch.setattr("app.workers.runner.service.observe_egress", observed)
    service = MediaRunnerService(settings(tmp_path))
    with pytest.raises(RunnerFailure) as caught:
        await service.inspect("https://www.youtube.com/watch?v=jNQXAC9IVRw")
    assert "global_residential/datacenter IP 8.8.8.8" in caught.value.failure.summary


async def test_observed_ip_reaches_layer_and_success_context(tmp_path, monkeypatch):
    from app.services.provider_types import Layer
    from app.workers.runner.engine.ladder import LAYER_TABLE
    from app.workers.runner.engine.resolved import ResolvedMedia
    from app.workers.runner.metadata import normalize_metadata
    from helpers import settings, split_media_info

    seen = []

    async def observed(binding, *, settings):
        return replace(binding, observed_ip="8.8.8.8")

    class SuccessfulLayer:
        async def resolve(self, source, ctx):
            seen.append(
                (ctx.egress.observed_ip, source.execution_context.egress_observed_ip)
            )
            media = normalize_metadata(
                split_media_info(),
                max_duration_seconds=86400,
                max_candidate_streams=200,
            )
            return ResolvedMedia(
                **{field.name: getattr(media, field.name) for field in fields(media)},
                client="yt-dlp-default",
            )

    monkeypatch.setattr("app.workers.runner.service.observe_egress", observed)
    monkeypatch.setitem(LAYER_TABLE, Layer.L1, SuccessfulLayer)
    response = await MediaRunnerService(settings(tmp_path)).inspect(
        "https://www.bilibili.com/video/BV13x41117TL"
    )
    assert seen == [("8.8.8.8", "8.8.8.8")]
    assert response.execution_context.egress_observed_ip == "8.8.8.8"
    assert response.execution_context.egress_route == "cn_residential"


def test_download_preflight_waits_for_fresh_ip_observation(tmp_path):
    from helpers import settings

    service = MediaRunnerService(settings(tmp_path))
    source = provider_request("https://www.bilibili.com/video/BV13x41117TL")
    expected = replace(service._context(source), egress_observed_ip="8.8.8.8")
    # A restart loses the observation cache, but should reobserve before deciding
    # that the previously observed node changed.
    egress._observations.clear()
    assert service._validate_context(source, expected) == expected


async def test_download_rejects_changed_ip_before_media_io(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from app.workers.runner.errors import RunnerFailure
    from helpers import settings

    service = MediaRunnerService(settings(tmp_path))
    source = provider_request("https://www.bilibili.com/video/BV13x41117TL")
    expected = replace(service._context(source), egress_observed_ip="8.8.8.8")

    async def observed(binding, *, settings):
        return replace(binding, observed_ip="1.1.1.1")

    async def unexpected(*args, **kwargs):
        pytest.fail("changed egress reached media I/O")

    monkeypatch.setattr("app.workers.runner.service.observe_egress", observed)
    monkeypatch.setattr("app.workers.runner.service.run_ladder", unexpected)
    with pytest.raises(RunnerFailure) as caught:
        await service._resolve_with_retries(
            source,
            None,
            context=expected,
            expected_context=expected,
            cookie_jar=None,
            deadline=datetime.now(UTC) + timedelta(seconds=5),
        )
    assert caught.value.code == "context_changed"
