"""Anonymous evidence must establish a restriction, never infer it from a wall."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.workers.runner import youtube_availability as module
from app.workers.runner.provider_registry import provider_request
from helpers import run_context, settings


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,reason,expected",
    [
        ("LOGIN_REQUIRED", "非公開動画", True),
        ("LOGIN_REQUIRED", "This video is private", True),
        ("ERROR", "This video has been deleted", True),
        ("LOGIN_REQUIRED", "Sign in to confirm you're not a bot", False),
        ("LOGIN_REQUIRED", "Sign in to confirm your age", False),
        ("UNPLAYABLE", "Video unavailable", False),
        ("OK", "This video is private", False),
    ],
)
async def test_explicit_player_reason_and_fixed_anonymous_transport(
    monkeypatch, tmp_path, status, reason, expected
):
    original = httpx.AsyncClient
    calls = []

    def transport(request):
        assert str(request.url) == "https://www.youtube.com/watch?v=s7_qI6_mIXc"
        assert (
            "cookie" not in request.headers and "authorization" not in request.headers
        )
        player = {"playabilityStatus": {"status": status, "reason": reason}}
        return httpx.Response(
            200, text="var ytInitialPlayerResponse = " + json.dumps(player)
        )

    def client(**kwargs):
        calls.append(dict(kwargs))
        kwargs.pop("proxy")
        return original(transport=httpx.MockTransport(transport), **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", client)
    ctx = run_context(settings(tmp_path), "youtube")
    assert (
        await module.explicit_content_restriction(
            provider_request("https://youtu.be/s7_qI6_mIXc"), ctx
        )
        is expected
    )
    assert calls[0]["proxy"] == ctx.egress.proxy_url
    assert calls[0]["follow_redirects"] is False
    assert calls[0]["trust_env"] is False
    assert 0 < calls[0]["timeout"] <= 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["redirect", "network", "oversized", "invalid", "missing"]
)
async def test_missing_evidence_preserves_original_failure(monkeypatch, tmp_path, mode):
    original = httpx.AsyncClient

    def transport(request):
        if mode == "network":
            raise httpx.ConnectError("controlled", request=request)
        if mode == "redirect":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})
        if mode == "oversized":
            return httpx.Response(200, content=b"x" * (module._MAX_PAGE_BYTES + 1))
        return httpx.Response(
            200,
            text="ytInitialPlayerResponse = broken"
            if mode == "invalid"
            else "no player",
        )

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(transport),
            **{k: v for k, v in kw.items() if k != "proxy"},
        ),
    )
    assert not await module.explicit_content_restriction(
        provider_request("https://www.youtube.com/watch?v=s7_qI6_mIXc"),
        run_context(settings(tmp_path), "youtube"),
    )


@pytest.mark.asyncio
async def test_deadline_other_platform_and_cancellation(monkeypatch, tmp_path):
    def unexpected(**_):
        raise AssertionError("no request expected")

    monkeypatch.setattr(module.httpx, "AsyncClient", unexpected)
    ctx = run_context(settings(tmp_path), "youtube")
    expired = replace(ctx, deadline=datetime.now(UTC) - timedelta(seconds=1))
    assert not await module.explicit_content_restriction(
        provider_request("https://youtu.be/s7_qI6_mIXc"), expired
    )
    assert not await module.explicit_content_restriction(
        provider_request("https://vimeo.com/123"), ctx
    )
    assert not await module.explicit_content_restriction(
        provider_request("https://youtu.be/invalid"), ctx
    )

    def cancelled(**_):
        raise asyncio.CancelledError

    monkeypatch.setattr(module.httpx, "AsyncClient", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await module.explicit_content_restriction(
            provider_request("https://youtu.be/s7_qI6_mIXc"), ctx
        )
