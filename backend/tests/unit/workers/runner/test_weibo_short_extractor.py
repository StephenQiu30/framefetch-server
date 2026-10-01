from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.plugins.yt_dlp_plugins.extractor import weibo_short
from app.workers.runner.provider_errors import (
    ProviderFailureContext,
    classify_provider_failure,
)
from app.workers.runner.provider_registry import provider_request
from yt_dlp.utils import ExtractorError  # type: ignore[import-untyped]

SHORT = "http://t.cn/Example1"
FID = "1034:1234567890123456"
VIDEO = f"https://weibo.com/tv/show/{FID}"


def extractor_with_transport(
    monkeypatch: pytest.MonkeyPatch,
    handle: Callable[[httpx.Request], httpx.Response],
) -> weibo_short.WeiboOfficialShortIE:
    extractor = weibo_short.WeiboOfficialShortIE()
    monkeypatch.setattr(extractor, "get_param", lambda _: "http://egress-proxy:3128")
    client_class = httpx.Client

    def client(**kwargs: object) -> httpx.Client:
        assert kwargs == {
            "proxy": "http://egress-proxy:3128",
            "trust_env": False,
            "follow_redirects": False,
            "timeout": 5.0,
        }
        return client_class(
            transport=httpx.MockTransport(handle), follow_redirects=False
        )

    monkeypatch.setattr(weibo_short.httpx, "Client", client)
    return extractor


@pytest.mark.parametrize(
    ("source", "canonical"),
    [
        (SHORT, "https://t.cn/Example1"),
        (f"https://video.weibo.com/show?fid={FID}&from=share", VIDEO),
        (f"https://www.weibo.com/tv/show/{FID}?from=share", VIDEO),
        ("https://www.weibo.com/123/AbCd?from=share", "https://weibo.com/123/AbCd"),
        (
            "https://m.weibo.cn/detail/12345?from=share",
            "https://m.weibo.cn/detail/12345",
        ),
        ("https://m.weibo.cn/status/AbCd", "https://m.weibo.cn/status/AbCd"),
    ],
)
def test_share_entries_keep_weibo_context(source: str, canonical: str) -> None:
    request = provider_request(source)
    assert request.profile.key == "weibo"
    assert request.source_url == source
    assert request.request_url == canonical


@pytest.mark.parametrize(
    "source",
    [
        "https://weibo.com/u/123",
        "https://weibo.com/123",
        "https://t.cn/",
        "https://t.cn/a/b",
        "https://video.weibo.com/show?fid=invalid",
        f"https://video.weibo.com/show?fid={FID}&fid={FID}",
    ],
)
def test_non_video_entries_are_rejected(source: str) -> None:
    with pytest.raises(RunnerFailure):
        provider_request(source)


@pytest.mark.parametrize(
    ("target", "canonical", "key"),
    [
        (f"https://video.weibo.com/show?fid={FID}", VIDEO, "WeiboVideo"),
        ("https://weibo.com/123/AbCd", "https://weibo.com/123/AbCd", "Weibo"),
        ("https://m.weibo.cn/detail/12345", "https://m.weibo.cn/detail/12345", "Weibo"),
    ],
)
def test_short_link_hands_off_before_visitor_page(
    monkeypatch: pytest.MonkeyPatch, target: str, canonical: str, key: str
) -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.url.host == "t.cn", "must not request the visitor landing page"
        return httpx.Response(302, headers={"Location": target})

    result = extractor_with_transport(monkeypatch, handle)._real_extract(SHORT)
    assert result["url"] == canonical
    assert result["ie_key"] == key
    assert calls == ["https://t.cn/Example1"]


@pytest.mark.parametrize(
    "target",
    [
        "http://127.0.0.1/private",
        "https://evil.test/video",
        "https://weibo.com.evil.test/123/AbCd",
        "https://weibo.com@evil.test/123/AbCd",
        "https://weibo.com:8443/123/AbCd",
        "https://passport.weibo.com/visitor/visitor",
        "https://weibo.com/u/123",
        "file:///private",
        "https://weibo.com/123/AbCd\n",
    ],
)
def test_short_link_never_follows_invalid_destination(
    monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": target})

    with pytest.raises(ExtractorError, match="provider_link_unavailable"):
        extractor_with_transport(monkeypatch, handle)._real_extract(SHORT)
    assert len(calls) == 1


def test_short_link_redirect_loop_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "/Example1"})

    with pytest.raises(ExtractorError, match="provider_link_unavailable"):
        extractor_with_transport(monkeypatch, handle)._real_extract(SHORT)
    assert len(calls) == 3


@pytest.mark.parametrize(
    ("status", "code", "mapped_status"),
    [
        (200, "provider_link_unavailable", 422),
        (404, "provider_link_unavailable", 422),
        (429, "provider_rate_limited", 429),
        (503, "provider_temporarily_unavailable", 503),
    ],
)
def test_short_link_failure_classification(
    monkeypatch: pytest.MonkeyPatch, status: int, code: str, mapped_status: int
) -> None:
    extractor = extractor_with_transport(monkeypatch, lambda _: httpx.Response(status))
    with pytest.raises(ExtractorError, match=code) as caught:
        extractor._real_extract(SHORT)
    assert classify_provider_failure(
        ProviderFailureContext("weibo", SHORT, False), str(caught.value).encode()
    ) == (
        {
            "provider_link_unavailable": "content_unavailable",
            "provider_rate_limited": "rate_limited",
            "provider_temporarily_unavailable": "transient",
        }[code],
        mapped_status,
    )


def test_plugin_is_discovered_by_production_command() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "yt_dlp",
            "--ignore-config",
            "--verbose",
            "--plugin-dirs",
            str(backend_root / "app/workers/runner"),
            "--simulate",
            "--",
            "file:///disabled",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert "WeiboOfficialShort" in result.stderr
