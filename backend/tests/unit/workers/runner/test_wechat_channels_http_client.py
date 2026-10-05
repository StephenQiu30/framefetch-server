"""Fixed authenticated HTTP-parse transport without real browser identity."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from app.services.provider_failures import FailureClass
from app.workers.identity.yuanbao_parse import YUANBAO_PARSE_URL
from app.workers.runner import wechat_channels_http as client
from app.workers.runner.engine.layers.base import LayerFailure
from app.workers.runner.wechat_channels_response import yuanbao_reference
from pydantic import SecretStr

SHARE = "https://weixin.qq.com/sph/SyntheticShare"
TOKEN = "synthetic-runner-only-bearer"
REFERENCE = (
    "https://channels.weixin.qq.com/finder-preview/pages/feed"
    "?token=synthetic-feed-ticket&eid=synthetic-export"
)


def deadline() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=120)


def captured() -> dict[str, Any]:
    return {
        "request_method": "POST",
        "request_url": YUANBAO_PARSE_URL,
        "response_url": YUANBAO_PARSE_URL,
        "http_status": 200,
        "request_body": {"type": "video_channel_url", "url": SHARE, "scene": 1},
        "payload": {"code": 0, "data": {"playable_url": REFERENCE}},
    }


class ReplyStream(httpx.AsyncByteStream):
    def __init__(self, state: SimpleNamespace) -> None:
        self.state = state

    async def __aiter__(self):
        self.state.started.set()
        if self.state.block:
            await asyncio.Event().wait()
        raw = self.state.raw
        if raw is None:
            raw = json.dumps(self.state.reply).encode()
        for start in range(0, len(raw), 1024):
            yield raw[start : start + 1024]

    async def aclose(self) -> None:
        self.state.closed = True


@pytest.fixture
def transport(monkeypatch):
    settings = SimpleNamespace(
        cookie_source_token=SecretStr(TOKEN),
        cookie_source_port=19101,
        runner_egress_proxy="http://controlled-proxy:3128",
    )
    state = SimpleNamespace(
        status=200,
        reply={"identity_digest": "a" * 64, "captured": captured()},
        raw=None,
        headers={},
        block=False,
        closed=False,
        started=asyncio.Event(),
        error=None,
    )
    requests: list[httpx.Request] = []
    options: list[dict[str, Any]] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if state.error is not None:
            raise state.error
        return httpx.Response(
            state.status, headers=state.headers, stream=ReplyStream(state)
        )

    original_client = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        options.append(dict(kwargs))
        assert kwargs.pop("proxy") == settings.runner_egress_proxy
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return original_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(client, "get_runner_settings", lambda: settings)
    monkeypatch.setattr(client.httpx, "AsyncClient", factory)
    return settings, state, requests, options


async def test_http_client_authenticates_only_to_the_fixed_configured_host(transport):
    settings, state, requests, options = transport
    settings.cookie_source_port = 19102
    end = deadline().astimezone(timezone(timedelta(hours=8)))

    result = await client.parse_yuanbao_share(SHARE, "task_123", end)

    assert result.identity.digest == "a" * 64
    assert result.captured == captured()
    assert "synthetic-feed-ticket" not in repr(result)
    assert REFERENCE not in repr(result)
    result.identity.cleanup()
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url == "http://host.docker.internal:19102/yuanbao-parse"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert "cookie" not in request.headers
    assert json.loads(request.content) == {
        "site": "wechat_channels",
        "canonical_share_url": SHARE,
        "task_id": "task_123",
        "deadline": end.astimezone(UTC).isoformat(),
    }
    assert options[0]["timeout"].read == 32.0
    assert state.closed


@pytest.mark.parametrize(
    "url",
    [
        "http://weixin.qq.com/sph/SyntheticShare",
        "https://weixin.qq.com.evil.test/sph/SyntheticShare",
        "https://weixin.qq.com:443/sph/SyntheticShare",
        "https://weixin.qq.com/sph/abc",
        SHARE + "/",
        SHARE + "?tracking=synthetic",
        SHARE + "#fragment",
    ],
)
async def test_invalid_share_never_contacts_host(transport, url):
    _, _, requests, _ = transport
    with pytest.raises(LayerFailure) as caught:
        await client.parse_yuanbao_share(url, "task", deadline())
    assert caught.value.failure.failure_class is FailureClass.INVALID_INPUT
    assert requests == []


@pytest.mark.parametrize("task", ["", "../task", "task with space", "x" * 129])
async def test_invalid_task_never_contacts_host(transport, task):
    _, _, requests, _ = transport
    with pytest.raises(LayerFailure):
        await client.parse_yuanbao_share(SHARE, task, deadline())
    assert requests == []


@pytest.mark.parametrize("end", [datetime.now(UTC), datetime(2030, 1, 1)])
async def test_expired_or_naive_deadline_never_contacts_host(transport, end):
    _, _, requests, _ = transport
    with pytest.raises(LayerFailure):
        await client.parse_yuanbao_share(SHARE, "task", end)
    assert requests == []


async def test_missing_bearer_never_contacts_host(transport):
    settings, _, requests, _ = transport
    settings.cookie_source_token = None
    with pytest.raises(LayerFailure) as caught:
        await client.parse_yuanbao_share(SHARE, "task", deadline())
    assert caught.value.failure.evidence["cause_code"] == "identity_not_configured"
    assert requests == []


@pytest.mark.parametrize(
    "change",
    [
        {"key": "instagram"},
        {"identity_source": "cookies"},
        {"identity_origin": "https://evil.test"},
        {"content_scope": "personal_full"},
        {"content_scope": "public"},
        {"cookie_domain_allowlist": frozenset({"yuanbao.tencent.com"})},
    ],
)
async def test_invalid_http_profile_never_contacts_host(transport, monkeypatch, change):
    _, _, requests, _ = transport
    profile = client.provider_profile_for_key("wechat_channels")
    values = {
        name: getattr(profile, name)
        for name in (
            "key",
            "identity_source",
            "identity_origin",
            "content_scope",
            "identity",
            "cookie_domain_allowlist",
        )
    }
    monkeypatch.setattr(
        client,
        "provider_profile_for_key",
        lambda _site: SimpleNamespace(**(values | change)),
    )
    with pytest.raises(LayerFailure) as caught:
        await client.parse_yuanbao_share(SHARE, "task", deadline())
    assert caught.value.failure.evidence["cause_code"] == "identity_source_mismatch"
    assert requests == []


@pytest.mark.parametrize(
    "change",
    [
        {"identity_digest": "invalid"},
        {"identity_digest": True},
        {"account_id": "synthetic-private-account"},
        {"auth_token": "synthetic-private-token"},
        {"captured": None},
    ],
)
async def test_invalid_or_extra_response_fields_fail_without_raw_material(
    transport, change
):
    _, state, _, _ = transport
    state.reply |= change
    with pytest.raises(LayerFailure) as caught:
        await client.parse_yuanbao_share(SHARE, "task", deadline())
    assert caught.value.failure.evidence["cause_code"] == "parse_response_invalid"
    assert "synthetic-private" not in str(caught.value)
    assert state.closed


@pytest.mark.parametrize(
    "change",
    [
        {"request_method": "GET"},
        {"request_url": YUANBAO_PARSE_URL + "?tracking=synthetic"},
        {"response_url": "https://evil.test/api/weixin/get_parse_result"},
        {"http_status": True},
        {"request_body": {"type": "video_channel_url", "url": SHARE, "scene": True}},
        {
            "request_body": {
                "type": "video_channel_url",
                "url": SHARE + "Other",
                "scene": 1,
            }
        },
        {"payload": []},
        {"headers": {"Authorization": "synthetic-private"}},
    ],
)
async def test_captured_request_metadata_must_match_this_fixed_share(transport, change):
    _, state, _, _ = transport
    state.reply["captured"] |= change
    with pytest.raises(LayerFailure) as caught:
        await client.parse_yuanbao_share(SHARE, "task", deadline())
    assert caught.value.failure.evidence["cause_code"] == "parse_response_invalid"
    assert "synthetic-private" not in str(caught.value)


async def test_missing_capture_field_cannot_be_substituted_by_nested_envelope(
    transport,
):
    _, state, _, _ = transport
    del state.reply["captured"]["request_url"]
    state.reply["captured"]["payload"] = {"request_url": YUANBAO_PARSE_URL, "code": 0}
    with pytest.raises(LayerFailure):
        await client.parse_yuanbao_share(SHARE, "task", deadline())


@pytest.mark.parametrize(
    "payload",
    [
        {"code": 401, "data": {"playable_url": REFERENCE}},
        {
            "code": 0,
            "data": {
                "playable_url": "https://evil.test/?token=synthetic&eid=synthetic"
            },
        },
        {"code": 0, "data": {"playable_url": REFERENCE + "&token=other"}},
        {"code": 0, "data": {"code": 0, "data": {"playable_url": REFERENCE}}},
    ],
)
async def test_transport_success_does_not_validate_business_envelopes_or_tickets(
    transport, payload
):
    _, state, _, _ = transport
    state.reply["captured"]["payload"] = payload
    result = await client.parse_yuanbao_share(SHARE, "task", deadline())
    assert result.captured["payload"] == payload
    assert yuanbao_reference(canonical_share_url=SHARE, **result.captured) is None


@pytest.mark.parametrize(
    ("cause", "kind"),
    [
        ("credential_missing", FailureClass.LOGIN_REQUIRED),
        ("identity_account_conflict", FailureClass.CONTEXT_CHANGED),
        ("extension_timeout", FailureClass.IDENTITY_UNAVAILABLE),
        ("yuanbao_request_rule_unavailable", FailureClass.IDENTITY_UNAVAILABLE),
        ("parse_response_invalid", FailureClass.EXTRACTOR_BROKEN),
        ("yuanbao_response_source_invalid", FailureClass.EXTRACTOR_BROKEN),
        ("yuanbao_response_size_invalid", FailureClass.EXTRACTOR_BROKEN),
        ("yuanbao_response_utf8_invalid", FailureClass.EXTRACTOR_BROKEN),
        ("yuanbao_response_json_invalid", FailureClass.EXTRACTOR_BROKEN),
        ("yuanbao_response_credential_echo", FailureClass.EXTRACTOR_BROKEN),
        ("parse_request_failed", FailureClass.TRANSIENT),
    ],
)
async def test_only_fixed_bridge_causes_are_classified(transport, cause, kind):
    _, state, _, _ = transport
    state.status = 503
    state.reply = {"cause": cause}
    with pytest.raises(LayerFailure) as caught:
        await client.parse_yuanbao_share(SHARE, "task", deadline())
    assert caught.value.failure.failure_class is kind
    assert caught.value.failure.evidence["cause_code"] == cause


@pytest.mark.parametrize(
    "reply",
    [
        {"cause": "synthetic-private-token"},
        {"cause": "credential_missing", "private": "synthetic-private-token"},
    ],
)
async def test_arbitrary_bridge_causes_and_extra_error_fields_do_not_escape(
    transport, reply
):
    _, state, _, _ = transport
    state.status = 503
    state.reply = reply
    with pytest.raises(LayerFailure) as caught:
        await client.parse_yuanbao_share(SHARE, "task", deadline())
    assert caught.value.failure.evidence["cause_code"] == "cookie_source_rejected"
    assert "synthetic-private" not in str(caught.value)


async def test_redirect_never_receives_bearer_at_another_host(transport):
    _, state, requests, _ = transport
    state.status = 307
    state.headers = {"location": "https://evil.test/collect"}
    with pytest.raises(LayerFailure):
        await client.parse_yuanbao_share(SHARE, "task", deadline())
    assert len(requests) == 1
    assert not state.started.is_set()
    assert state.closed


@pytest.mark.parametrize(
    "length", [str(client._MAX_RESPONSE_BYTES + 1), "9" * 5000, "invalid"]
)
async def test_declared_oversized_or_invalid_length_fails_before_stream_read(
    transport, length
):
    _, state, _, _ = transport
    state.headers = {"content-length": length}
    with pytest.raises(LayerFailure):
        await client.parse_yuanbao_share(SHARE, "task", deadline())
    assert not state.started.is_set()
    assert state.closed


async def test_chunked_payload_is_bounded_before_accumulation(transport, monkeypatch):
    _, state, _, _ = transport
    monkeypatch.setattr(client, "_MAX_RESPONSE_BYTES", 1024)
    state.raw = b"x" * 2048
    with pytest.raises(LayerFailure) as caught:
        await client.parse_yuanbao_share(SHARE, "task", deadline())
    assert caught.value.failure.evidence["cause_code"] == "parse_response_invalid"
    assert state.closed


@pytest.mark.parametrize(
    "raw",
    [
        b"synthetic-private-not-json",
        b'{"identity_digest":"a","identity_digest":"b","captured":{}}',
        b'{"identity_digest":NaN,"captured":{}}',
    ],
)
async def test_ambiguous_invalid_json_never_exposes_raw_text(transport, raw):
    _, state, _, _ = transport
    state.raw = raw
    with pytest.raises(LayerFailure) as caught:
        await client.parse_yuanbao_share(SHARE, "task", deadline())
    assert "synthetic-private" not in str(caught.value)
    assert caught.value.failure.evidence["cause_code"] == "parse_response_invalid"


async def test_transport_timeout_closes_stream_and_cannot_return_late_result(
    transport, monkeypatch
):
    _, state, _, _ = transport
    state.block = True
    monkeypatch.setattr(client, "_TRANSPORT_TIMEOUT", 0.01)
    with pytest.raises(LayerFailure) as caught:
        await client.parse_yuanbao_share(SHARE, "task", deadline())
    assert caught.value.failure.evidence["cause_code"] == "extension_timeout"
    assert state.closed


async def test_cancelled_transport_closes_stream_and_propagates_cancellation(transport):
    _, state, _, _ = transport
    state.block = True
    operation = asyncio.create_task(
        client.parse_yuanbao_share(SHARE, "task", deadline())
    )
    await state.started.wait()
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert state.closed


async def test_response_completed_at_operation_deadline_is_rejected(
    transport, monkeypatch
):
    _, state, _, _ = transport
    current = datetime.now(UTC)

    class Clock(datetime):
        calls = 0

        @classmethod
        def now(cls, _tz=None):
            cls.calls += 1
            return current if cls.calls == 1 else current + timedelta(seconds=30)

    monkeypatch.setattr(client, "datetime", Clock)
    end = Clock.fromtimestamp((current + timedelta(seconds=30)).timestamp(), UTC)
    with pytest.raises(LayerFailure) as caught:
        await client.parse_yuanbao_share(SHARE, "task", end)
    assert caught.value.failure.evidence["cause_code"] == "identity_deadline_invalid"
    assert state.closed


async def test_transport_exception_does_not_export_exception_text(transport):
    _, state, _, _ = transport
    state.error = httpx.ConnectError("synthetic-private-account-token")
    with pytest.raises(LayerFailure) as caught:
        await client.parse_yuanbao_share(SHARE, "task", deadline())
    assert caught.value.failure.evidence["cause_code"] == "cookie_source_unavailable"
    assert "synthetic-private" not in str(caught.value)
