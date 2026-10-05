"""Bounded official-share resolution with synthetic native and HTTP evidence."""

from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from app.services.provider_failures import FailureClass
from app.workers.runner.engine.browser import wechat_channels as channels
from app.workers.runner.engine.identity import YuanbaoRequestIdentity
from app.workers.runner.engine.layers.base import LayerFailure
from app.workers.runner.engine.layers.browser import BrowserLayer
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import provider_request
from app.workers.runner.service import MediaRunnerService
from app.workers.runner.wechat_channels_http import ShareParseResult
from helpers import settings
from test_engine_skeleton import source_for

SHARE = "https://weixin.qq.com/sph/SyntheticShare"
PREVIEW = "https://channels.weixin.qq.com/finder-preview/pages/sph?id=SyntheticShare"
FEED = "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"
PARSE = "https://yuanbao.tencent.com/api/weixin/get_parse_result"
MEDIA = "https://finder.video.qq.com/251/20304/stodownload?encfilekey=synthetic-one"
COVER = "https://finder.video.qq.com/251/20304/cover.jpg"
DIGEST = "a" * 64


def feed_payload(*, media: bool = False) -> dict[str, Any]:
    feed: dict[str, Any] = {
        "description": "Synthetic official share",
        "coverUrl": COVER + "?ticket=anonymous",
    }
    if media:
        feed["mediaType"] = 4
        feed["coverUrl"] = COVER + "?ticket=official"
        feed["h264VideoInfo"] = {"videoUrl": MEDIA, "width": 1, "height": 1}
        feed["h265VideoInfo"] = {
            "videoUrl": MEDIA.replace("one", "two"),
            "width": 2,
            "height": 2,
        }
    return {
        "errCode": 0,
        "data": {
            "feedInfo": feed,
            "authorInfo": {"nickname": "Synthetic creator"},
            "errMsg": {"type": 0},
        },
    }


def native_capture() -> dict[str, Any]:
    return {
        "request_method": "POST",
        "request_url": PARSE,
        "response_url": PARSE,
        "http_status": 200,
        "request_body": {"type": "video_channel_url", "url": SHARE, "scene": 1},
        "payload": {
            "code": 0,
            "data": {
                "desc": "Synthetic\n official   share",
                "author": "Synthetic\tcreator",
                "cover_url": COVER + "?ticket=native",
                "playable_url": (
                    "https://channels.weixin.qq.com/finder-preview/pages/feed"
                    "?token=synthetic%252Fticket&eid=synthetic%252Fexport"
                    "&entry_card_type=5"
                ),
            },
        },
    }


def media_probe(codec: str = "h264", duration: str = "12.5") -> dict[str, Any]:
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": codec,
                "width": 1280,
                "height": 720,
                "avg_frame_rate": "30/1",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": duration, "size": "2500000"},
    }


class ReplyStream(httpx.AsyncByteStream):
    def __init__(self, state: SimpleNamespace, raw: bytes) -> None:
        self.state, self.raw = state, raw

    async def __aiter__(self):
        self.state.started.set()
        if self.state.block:
            await asyncio.Event().wait()
        for offset in range(0, len(self.raw), 1024):
            yield self.raw[offset : offset + 1024]

    async def aclose(self) -> None:
        self.state.closed += 1


@pytest.fixture
def operation(tmp_path, monkeypatch):
    config = settings(tmp_path)
    service = MediaRunnerService(config)
    base = source_for(service, tmp_path)
    request = provider_request(SHARE)
    source = replace(
        base,
        request=request,
        execution_context=service._context(request),
        run_context=replace(
            base.run_context,
            egress=replace(
                base.run_context.egress, proxy_url="http://selected-proxy:3128"
            ),
        ),
    )
    monkeypatch.setattr(source.pipeline, "browser", None)
    state = SimpleNamespace(
        anonymous=feed_payload(),
        official=feed_payload(media=True),
        capture=native_capture(),
        digest=DIGEST,
        statuses=[200, 201, 201],
        raw={},
        headers={},
        block=False,
        closed=0,
        started=asyncio.Event(),
        native_block=False,
        probe_block=False,
        probes=[media_probe("vp9"), media_probe("hevc")],
        error=None,
    )
    requests: list[httpx.Request] = []
    clients: list[dict[str, Any]] = []
    steps: list[str] = []
    contexts = []

    async def respond(request: httpx.Request) -> httpx.Response:
        index = len(requests)
        requests.append(request)
        steps.append(("preview", "anonymous", "official")[index])
        if state.error is not None:
            raise state.error
        raw = state.raw.get(index)
        if raw is None:
            raw = (
                b"<html>fixed preview</html>"
                if index == 0
                else json.dumps(
                    state.anonymous if index == 1 else state.official
                ).encode()
            )
        headers = state.headers.get(index, {})
        if index == 0:
            headers = {"set-cookie": "undeclared=synthetic; Path=/", **headers}
        return httpx.Response(
            state.statuses[index], headers=headers, stream=ReplyStream(state, raw)
        )

    original_client = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        clients.append(dict(kwargs))
        assert kwargs.pop("proxy") == "http://selected-proxy:3128"
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return original_client(transport=httpx.MockTransport(respond), **kwargs)

    async def native(canonical_url, task_id, end):
        assert canonical_url == SHARE
        assert task_id == source.workspace.path.name
        assert end == source.run_context.deadline or end < source.run_context.deadline
        steps.append("native")
        if state.native_block:
            await asyncio.Event().wait()
        return ShareParseResult(
            YuanbaoRequestIdentity(state.digest), copy.deepcopy(state.capture)
        )

    async def probe(url, cwd, *, referer):
        assert cwd == source.workspace.path and referer == PREVIEW
        steps.append("probe")
        if state.probe_block:
            await asyncio.Event().wait()
        result = state.probes.pop(0)
        if isinstance(result, BaseException):
            raise result
        return copy.deepcopy(result)

    def with_context(ctx):
        contexts.append(ctx)
        return SimpleNamespace(probe_remote=probe)

    monkeypatch.setattr(channels.httpx, "AsyncClient", factory)
    monkeypatch.setattr(channels, "parse_yuanbao_share", native)
    monkeypatch.setattr(source.pipeline._commands, "with_context", with_context)
    try:
        yield source, state, requests, clients, steps, contexts
    finally:
        source.workspace.cleanup()


async def test_l3_uses_bound_native_parse_and_actual_clear_file_specs(operation):
    source, state, requests, clients, steps, contexts = operation
    assert source.pipeline.browser is None

    result = await BrowserLayer().resolve(source, source.run_context)

    assert BrowserLayer.has_parser("wechat_channels")
    assert steps == ["preview", "anonymous", "native", "official", "probe", "probe"]
    assert [(request.method, str(request.url)) for request in requests] == [
        ("GET", PREVIEW),
        ("POST", FEED),
        ("POST", FEED),
    ]
    assert json.loads(requests[1].content) == {
        "baseReq": {"generalToken": ""},
        "shortUri": "SyntheticShare",
    }
    # %252F is decoded once to the opaque %2F ticket, never to a slash.
    assert json.loads(requests[2].content) == {
        "baseReq": {"generalToken": "synthetic%2Fticket"},
        "exportId": "synthetic%2Fexport",
    }
    assert all(
        "cookie" not in request.headers and "authorization" not in request.headers
        for request in requests
    )
    assert all(options["timeout"] <= 5 for options in clients)
    assert state.closed == 3
    assert result.client == channels.CLIENT and result.handoff == "http"
    assert result.provider_media_id == "SyntheticShare"
    assert (
        result.title == "Synthetic official share" and result.duration_seconds == 12.5
    )
    assert result.extractor_key == "WechatChannelsPublic"
    assert [item["vcodec"] for item in result.download_info["formats"]] == [
        "vp9",
        "hevc",
    ]
    assert all(
        item["width"] == 1280 and item["height"] == 720 and item["fps"] == 30
        for item in result.download_info["formats"]
    )
    assert (
        not {"availability", "_framefetch_full_stream", "original_duration"}
        & result.download_info.keys()
    )
    assert result.run_context is contexts[0]
    assert result.run_context.identity == YuanbaoRequestIdentity(DIGEST)
    assert result.run_context.cookie_file is None and result.run_context.browser is None
    assert result.run_context.egress == source.run_context.egress


@pytest.mark.parametrize("stage", ["anonymous", "native", "official"])
@pytest.mark.parametrize(
    "flag,kind",
    [
        ("isEncrypted", FailureClass.CONTENT_PROTECTED),
        ("isFollowOnly", FailureClass.CONTENT_UNAVAILABLE),
    ],
)
async def test_explicit_protection_or_restriction_stops_at_each_stage(
    operation, stage, flag, kind
):
    source, state, _, _, steps, _ = operation
    payload = state.capture["payload"] if stage == "native" else getattr(state, stage)
    payload["data"]["limits"] = {"nested": [{flag: "1"}]}

    with pytest.raises(LayerFailure) as caught:
        await channels.resolve(source, source.run_context)

    assert caught.value.failure.failure_class is kind
    assert "probe" not in steps
    if stage == "anonymous":
        assert "native" not in steps
    elif stage == "native":
        assert "official" not in steps


@pytest.mark.parametrize(
    "field,value",
    [("description", "Other work"), ("coverUrl", COVER.replace("cover", "other"))],
)
async def test_feed_work_mismatch_never_probes_or_downloads(operation, field, value):
    source, state, _, _, steps, _ = operation
    state.official["data"]["feedInfo"][field] = value
    with pytest.raises(LayerFailure) as caught:
        await channels.resolve(source, source.run_context)
    assert caught.value.failure.failure_class is FailureClass.CONTEXT_CHANGED
    assert "probe" not in steps


async def test_author_mismatch_and_missing_metadata_fail_closed(operation):
    source, state, _, _, steps, _ = operation
    state.capture["payload"]["data"]["author"] = "Other creator"
    with pytest.raises(LayerFailure) as caught:
        await channels.resolve(source, source.run_context)
    assert caught.value.failure.failure_class is FailureClass.CONTEXT_CHANGED
    assert "probe" not in steps


@pytest.mark.parametrize("field", ["desc", "author", "cover_url"])
async def test_missing_native_binding_metadata_never_probes(operation, field):
    source, state, _, _, steps, _ = operation
    del state.capture["payload"]["data"][field]
    with pytest.raises(LayerFailure) as caught:
        await channels.resolve(source, source.run_context)
    assert caught.value.failure.failure_class is FailureClass.EXTRACTOR_BROKEN
    assert "probe" not in steps


@pytest.mark.parametrize(
    "url",
    [
        SHARE + "?x=synthetic",
        SHARE + "#fragment",
        SHARE.replace("weixin.qq.com", "evil.example"),
    ],
)
async def test_noncanonical_share_never_requests_native_or_http(operation, url):
    source, _, requests, _, steps, _ = operation
    source = replace(source, request=replace(source.request, source_url=url))
    with pytest.raises(LayerFailure) as caught:
        await channels.resolve(source, source.run_context)
    assert caught.value.failure.failure_class is FailureClass.INVALID_INPUT
    assert not requests and not steps


async def test_generic_browser_identity_cannot_enter_native_resolver(operation):
    source, _, requests, _, steps, _ = operation
    ctx = replace(source.run_context, browser=SimpleNamespace())
    with pytest.raises(LayerFailure):
        await channels.resolve(source, ctx)
    assert not requests and not steps


async def test_changed_account_digest_stops_before_official_feed(operation):
    source, _, requests, _, steps, _ = operation
    expected = replace(
        source.execution_context,
        client=channels.CLIENT,
        identity_used=True,
        identity_digest="b" * 64,
    )
    source = replace(source, expected_context=expected)
    with pytest.raises(LayerFailure) as caught:
        await channels.resolve(source, source.run_context)
    assert caught.value.failure.failure_class is FailureClass.CONTEXT_CHANGED
    assert len(requests) == 2 and steps == ["preview", "anonymous", "native"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_method", "GET"),
        ("response_url", PARSE + "?different=1"),
        ("http_status", 401),
    ],
)
async def test_native_capture_binding_rejects_changed_request(operation, field, value):
    source, state, requests, _, steps, _ = operation
    state.capture[field] = value
    with pytest.raises(LayerFailure) as caught:
        await channels.resolve(source, source.run_context)
    assert caught.value.failure.evidence["cause_code"] == "native_reference_invalid"
    assert len(requests) == 2 and "probe" not in steps


@pytest.mark.parametrize(
    "status,kind",
    [
        (302, FailureClass.EXTRACTOR_BROKEN),
        (403, FailureClass.EXTRACTOR_BROKEN),
        (429, FailureClass.RATE_LIMITED),
        (503, FailureClass.TRANSIENT),
    ],
)
async def test_preview_status_never_follows_redirect_or_attempts_native(
    operation, status, kind
):
    source, state, requests, _, steps, _ = operation
    state.statuses[0] = status
    state.headers[0] = {"location": "https://evil.example/secret"}
    with pytest.raises(LayerFailure) as caught:
        await channels.resolve(source, source.run_context)
    assert caught.value.failure.failure_class is kind
    assert len(requests) == 1 and steps == ["preview"]
    assert "secret" not in str(caught.value.failure.evidence)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"errCode":0,"errCode":1}',
        b'{"errCode":NaN}',
        b"not json",
        b"\xff",
        pytest.param(b"[" * 20_000 + b"0" + b"]" * 20_000, id="deep-json"),
    ],
)
async def test_ambiguous_or_invalid_anonymous_json_never_calls_native(operation, raw):
    source, state, _, _, steps, _ = operation
    state.raw[1] = raw
    with pytest.raises(LayerFailure) as caught:
        await channels.resolve(source, source.run_context)
    assert caught.value.failure.evidence["cause_code"] == "official_response_invalid"
    assert "native" not in steps


@pytest.mark.parametrize("length", ["4194305", "-1", "1e10", "9" * 21, "١٢"])
async def test_declared_body_limit_is_strict(operation, length):
    source, state, _, _, steps, _ = operation
    # Non-ASCII header text cannot be emitted by HTTPX's header encoder. Raw
    # bytes here exercise the received header value rather than a client API.
    state.headers[1] = {b"content-length": length.encode("utf-8")}
    with pytest.raises(LayerFailure) as caught:
        await channels.resolve(source, source.run_context)
    assert caught.value.failure.evidence["cause_code"] == "official_response_size_limit"
    assert "native" not in steps


async def test_stream_limit_and_wide_structure_limit_never_call_native(operation):
    source, state, _, _, steps, _ = operation
    state.raw[1] = b" " * (channels.MAX_RESPONSE_BYTES + 1)
    with pytest.raises(LayerFailure) as caught:
        await channels.resolve(source, source.run_context)
    assert caught.value.failure.evidence["cause_code"] == "official_response_size_limit"
    assert "native" not in steps


async def test_wide_metadata_is_not_silently_truncated_for_restriction_scan(operation):
    source, state, _, _, steps, _ = operation
    state.anonymous["data"]["extra"] = [None] * 10_001
    with pytest.raises(LayerFailure) as caught:
        await channels.resolve(source, source.run_context)
    assert caught.value.failure.evidence["cause_code"] == "response_structure_limit"
    assert "native" not in steps


@pytest.mark.parametrize("stage", ["http", "native", "probe"])
async def test_task_deadline_cancels_each_resolution_stage(operation, stage):
    source, state, _, _, _, _ = operation
    source = replace(
        source,
        run_context=replace(
            source.run_context, deadline=datetime.now(UTC) + timedelta(milliseconds=35)
        ),
    )
    setattr(
        state,
        {"http": "block", "native": "native_block", "probe": "probe_block"}[stage],
        True,
    )
    with pytest.raises(TimeoutError):
        await channels.resolve(source, source.run_context)
    assert state.closed == {"http": 1, "native": 2, "probe": 3}[stage]


async def test_http_failure_is_sanitized(operation):
    source, state, _, _, _, _ = operation
    state.error = httpx.ConnectError("synthetic-secret-token must not escape")
    with pytest.raises(LayerFailure) as caught:
        await channels.resolve(source, source.run_context)
    assert caught.value.failure.failure_class is FailureClass.NETWORK_BLOCKED
    assert "synthetic-secret-token" not in str(caught.value)
    assert "synthetic-secret-token" not in str(caught.value.failure.evidence)


@pytest.mark.parametrize(
    "bad",
    [
        {"streams": []},
        media_probe(duration="nan"),
        media_probe(duration="0"),
        {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1280,
                    "height": 720,
                    "avg_frame_rate": "30/1",
                }
            ],
            "format": {"duration": "12.5"},
        },
    ],
)
async def test_missing_actual_codec_video_or_duration_never_invents_candidate(
    operation, bad
):
    source, state, _, _, _, _ = operation
    state.probes = [bad, copy.deepcopy(bad)]
    with pytest.raises(LayerFailure) as caught:
        await channels.resolve(source, source.run_context)
    assert caught.value.failure.failure_class is FailureClass.FORMAT_UNAVAILABLE


async def test_failed_candidate_can_yield_to_another_probed_official_candidate(
    operation,
):
    source, state, _, _, _, _ = operation
    state.probes = [RunnerFailure("media_probe_failed"), media_probe("vp9")]
    result = await channels.resolve(source, source.run_context)
    assert (
        len(result.streams) == 1
        and result.download_info["formats"][0]["vcodec"] == "vp9"
    )


async def test_protected_probe_failure_is_never_ignored(operation):
    source, state, _, _, steps, _ = operation
    state.probes = [RunnerFailure("content_protected"), media_probe()]
    with pytest.raises(RunnerFailure) as caught:
        await channels.resolve(source, source.run_context)
    assert caught.value.failure.failure_class is FailureClass.CONTENT_PROTECTED
    assert steps.count("probe") == 1


async def test_candidate_duration_mismatch_never_establishes_single_source(operation):
    source, state, _, _, _, _ = operation
    state.probes = [media_probe(duration="12.5"), media_probe(duration="30")]
    with pytest.raises(LayerFailure) as caught:
        await channels.resolve(source, source.run_context)
    assert caught.value.failure.evidence["cause_code"] == "candidate_duration_mismatch"


@pytest.mark.parametrize(
    "field,value",
    [
        ("width", 10**500),
        ("width", True),
        ("codec_name", "unknown"),
        ("avg_frame_rate", "0/0"),
    ],
)
async def test_malformed_actual_video_specs_are_not_candidates(operation, field, value):
    source, state, _, _, _, _ = operation
    probe = media_probe()
    probe["streams"][0][field] = value
    state.probes = [probe, copy.deepcopy(probe)]
    with pytest.raises(LayerFailure) as caught:
        await channels.resolve(source, source.run_context)
    assert caught.value.failure.failure_class is FailureClass.FORMAT_UNAVAILABLE


async def test_present_audio_stream_requires_actual_codec(operation):
    source, state, _, _, _, _ = operation
    probe = media_probe()
    del probe["streams"][1]["codec_name"]
    state.probes = [probe, copy.deepcopy(probe)]
    with pytest.raises(LayerFailure):
        await channels.resolve(source, source.run_context)


async def test_observed_video_only_file_does_not_invent_audio(operation):
    source, state, _, _, _, _ = operation
    probe = media_probe()
    probe["streams"].pop()
    state.probes = [probe, copy.deepcopy(probe)]
    result = await channels.resolve(source, source.run_context)
    assert all(item["acodec"] == "none" for item in result.download_info["formats"])


async def test_candidate_url_gate_runs_before_probe(operation):
    source, state, _, _, steps, _ = operation
    feed = state.official["data"]["feedInfo"]
    for key in ("h264VideoInfo", "h265VideoInfo"):
        feed[key]["videoUrl"] = "https://evil.example/251/20304/stodownload"
    with pytest.raises(LayerFailure) as caught:
        await channels.resolve(source, source.run_context)
    assert caught.value.failure.failure_class is FailureClass.FORMAT_UNAVAILABLE
    assert "probe" not in steps


@pytest.mark.parametrize("stage", ["anonymous", "official"])
@pytest.mark.parametrize("page_type", [1, 2, 3, 4, "0", False, None])
async def test_errcode_zero_cannot_bypass_official_page_state(
    operation, stage, page_type
):
    source, state, _, _, steps, _ = operation
    getattr(state, stage)["data"]["errMsg"]["type"] = page_type
    with pytest.raises(LayerFailure):
        await channels.resolve(source, source.run_context)
    assert "probe" not in steps
    if stage == "anonymous":
        assert "native" not in steps


@pytest.mark.parametrize("stage", ["anonymous", "official"])
@pytest.mark.parametrize("media_type", [2, "4", True, None])
async def test_explicit_nonvideo_or_malformed_media_type_is_rejected(
    operation, stage, media_type
):
    source, state, _, _, steps, _ = operation
    getattr(state, stage)["data"]["feedInfo"]["mediaType"] = media_type
    with pytest.raises(LayerFailure) as caught:
        await channels.resolve(source, source.run_context)
    assert caught.value.failure.evidence["cause_code"] == "official_video_type_invalid"
    assert "probe" not in steps


async def test_official_feed_requires_observed_video_media_type(operation):
    source, state, _, _, steps, _ = operation
    del state.official["data"]["feedInfo"]["mediaType"]
    with pytest.raises(LayerFailure):
        await channels.resolve(source, source.run_context)
    assert "probe" not in steps


async def test_l3_native_dispatch_never_enters_generic_browser_runtime(
    operation, monkeypatch
):
    source, _, _, _, _, _ = operation
    runtime = SimpleNamespace(
        acquire=AsyncMock(side_effect=AssertionError("generic acquire"))
    )
    monkeypatch.setattr(source.pipeline, "browser", runtime)
    await BrowserLayer().resolve(source, source.run_context)
    runtime.acquire.assert_not_called()
