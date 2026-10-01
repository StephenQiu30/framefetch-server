"""Deterministic page oracle, material lifetime and first-party parser evidence."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from app.services.provider_failures import FailureClass
from app.services.provider_types import ProviderIdentity
from app.workers.runner.engine import identity
from app.workers.runner.engine.browser import douyin, kuaishou, weibo, xiaohongshu
from app.workers.runner.engine.browser.intercept import (
    MAX_RESPONSE_BYTES,
    PageResponses,
)
from app.workers.runner.engine.layers.browser import BrowserLayer
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import provider_request
from app.workers.runner.service import MediaRunnerService
from helpers import settings
from test_engine_skeleton import source_for
from test_g2_browser import status

NOTE_ID = "6a82c08c0000000029032447"
MEDIA = "https://media.example.org/video.mp4"


def douyin_payload(work="123"):
    return {
        "aweme_detail": {
            "aweme_id": work,
            "desc": "公开作品",
            "status": {"private_status": 0},
            "video": {
                "duration": 12000,
                "width": 1280,
                "height": 720,
                "play_addr": {"url_list": [MEDIA]},
            },
        }
    }


def xhs_payload():
    return {
        "data": {
            "items": [
                {
                    "note_card": {
                        "note_id": NOTE_ID,
                        "title": "公开视频",
                        "video": {
                            "consumer": {"duration": 12},
                            "media": {
                                "stream": {
                                    "h264": [
                                        {
                                            "master_url": MEDIA,
                                            "width": 1280,
                                            "height": 720,
                                            "duration": 12000,
                                        }
                                    ]
                                }
                            },
                        },
                    }
                }
            ]
        }
    }


@pytest.mark.parametrize(
    "parser,payload,work",
    [(douyin, douyin_payload(), "123"), (xiaohongshu, xhs_payload(), NOTE_ID)],
)
def test_first_party_video_identity_duration_and_formats(parser, payload, work):
    result = parser.parse_response(payload, work)
    assert result.provider_media_id == work and result.duration_seconds == 12
    assert result.client == f"{parser.RULES.platform}:browser"
    assert result.handoff == "http"
    assert result.download_info["formats"][0]["url"] == MEDIA
    with pytest.raises(RunnerFailure) as caught:
        parser.parse_response(payload, "other-work")
    assert caught.value.failure.failure_class is FailureClass.EXTRACTOR_BROKEN


@pytest.mark.parametrize(
    "flag,kind",
    [
        ("is_charge_content", FailureClass.CONTENT_UNAVAILABLE),
        ("is_private", FailureClass.CONTENT_UNAVAILABLE),
        ("is_preview", FailureClass.CONTENT_UNAVAILABLE),
        ("has_drm", FailureClass.CONTENT_PROTECTED),
        ("is_encrypt", FailureClass.CONTENT_PROTECTED),
    ],
)
def test_restrictions_and_protection_never_become_public(flag, kind):
    payload = douyin_payload()
    payload["aweme_detail"][flag] = True
    with pytest.raises(RunnerFailure) as caught:
        douyin.parse_response(payload)
    assert caught.value.failure.failure_class is kind


@pytest.mark.parametrize(
    "code,kind",
    [(300031, FailureClass.CONTENT_UNAVAILABLE), (300012, FailureClass.CHALLENGE)],
)
def test_xhs_explicit_availability_boundary(code, kind):
    with pytest.raises(RunnerFailure) as caught:
        xiaohongshu.parse_response({"code": code})
    assert caught.value.failure.failure_class is kind


async def test_interception_first_party_path_and_bounded_body():
    page = SimpleNamespace(on=lambda *args: None, remove_listener=lambda *args: None)
    collector = PageResponses(page, "douyin", douyin.RULES.response_patterns)
    body = AsyncMock(return_value=json.dumps(douyin_payload()).encode())
    response = SimpleNamespace(
        url="https://www.douyin.com/aweme/v1/web/aweme/detail/?signature=fixture",
        status=200,
        headers={},
        body=body,
    )
    collector._response(response)
    await asyncio.gather(*collector.tasks)
    assert collector.queue.get_nowait() == douyin_payload()
    collector._response(
        SimpleNamespace(
            url="https://other.example/aweme/v1/web/aweme/detail/",
            status=200,
            headers={},
            body=body,
        )
    )
    collector._response(
        SimpleNamespace(
            url=response.url,
            status=200,
            headers={"content-length": str(MAX_RESPONSE_BYTES + 1)},
            body=body,
        )
    )
    await asyncio.gather(*collector.tasks)
    assert body.await_count == 1
    await collector.close()


@pytest.mark.parametrize("handoff", ["http", "browser"])
@pytest.mark.parametrize(
    "parser,url,payload,work",
    [
        (douyin, "https://www.douyin.com/video/123", douyin_payload(), "123"),
        (
            kuaishou,
            "https://www.kuaishou.com/short-video/123",
            {
                "photo": {
                    "id": "123",
                    "photoUrl": MEDIA,
                    "durationMs": 12000,
                    "width": 1280,
                    "height": 720,
                }
            },
            "123",
        ),
        (weibo, "https://weibo.com/123/Abc", status(), "123"),
    ],
)
async def test_home_initialization_material_handoff_and_terminal_cleanup(
    tmp_path, monkeypatch, handoff, parser, url, payload, work
):
    service = MediaRunnerService(settings(tmp_path))
    source = source_for(service, tmp_path)
    source = replace(source, request=provider_request(url))
    monkeypatch.setattr(identity, "COOKIE_TMPFS_ROOT", tmp_path / "private")
    monkeypatch.setattr(identity, "validate_cookie_file", lambda _: None)
    events = []
    page = SimpleNamespace(url=source.request.source_url)
    page.on = lambda name, callback: events.append("intercept")
    page.remove_listener = lambda *args: None
    page.wait_for_timeout = AsyncMock()
    page.close = AsyncMock()
    page.evaluate = AsyncMock(return_value=json.dumps(payload))
    operation = SimpleNamespace(
        page=page,
        user_agent="browser-UA",
        cookies=AsyncMock(
            return_value=[
                {
                    "domain": f".{parser.RULES.platform}.com",
                    "name": "visitor",
                    "value": "fixture",
                    "path": "/",
                    "expires": -1,
                }
            ]
        ),
        close=AsyncMock(),
        abort=AsyncMock(),
        download=AsyncMock(),
    )

    async def navigate(url):
        events.append(url)
        if handoff == "browser" and url == source.request.source_url:
            callback = captured[0]
            callback(
                SimpleNamespace(
                    url=MEDIA, status=200, headers={"content-type": "video/mp4"}
                )
            )

    captured = []

    def listen(name, callback):
        events.append("intercept")
        captured.append(callback)

    page.on = listen
    operation.navigate = navigate
    runtime = SimpleNamespace(acquire=AsyncMock(return_value=operation))
    source.pipeline.browser = runtime
    probe = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1280,
                "height": 720,
                "avg_frame_rate": "30/1",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "12"},
    }
    source.pipeline._commands.probe_remote = AsyncMock(return_value=probe)
    if handoff == "browser":
        source.pipeline._commands.probe_remote.side_effect = RunnerFailure("challenge")
    result = await BrowserLayer().resolve(source, source.run_context)
    assert events == [parser.HOME, "intercept", source.request.source_url]
    assert result.provider_media_id == work
    assert result.client == f"{parser.RULES.platform}:browser"
    assert result.handoff == handoff
    assert page.close.await_count == (1 if handoff == "http" else 0)
    ctx = result.run_context
    assert ctx.cookie_file.is_file() and ctx.user_agent == "browser-UA"
    assert ctx.identity is None and "fixture" not in repr(ctx)
    assert ctx.cookie_file.stat().st_mode & 0o777 == 0o600
    assert ctx.cookie_file.parent.stat().st_mode & 0o777 == 0o700
    if handoff == "browser":
        await ctx.browser.download(MEDIA, tmp_path / "output.mp4")
        operation.download.assert_awaited_once()
        operation.close.assert_not_awaited()
    await ctx.browser.close()
    operation.close.assert_awaited_once()
    assert not ctx.cookie_file.parent.exists()
    source.workspace.cleanup()


async def test_required_identity_comes_only_from_fetch_identity(tmp_path, monkeypatch):
    service = MediaRunnerService(settings(tmp_path))
    source = source_for(service, tmp_path)
    request = provider_request("https://www.douyin.com/video/123")
    request = replace(
        request, profile=replace(request.profile, identity=ProviderIdentity.REQUIRED)
    )
    source = replace(source, request=request)
    monkeypatch.setattr(identity, "validate_cookie_file", lambda _: None)
    jar = tmp_path / "approved"
    jar.write_text("fixture")
    material = identity.IdentityMaterial(jar, "mock-digest")
    fetch = AsyncMock(return_value=material)
    monkeypatch.setattr(identity, "fetch_identity", fetch)
    acquire = AsyncMock(side_effect=RunnerFailure("runtime_unavailable"))
    source.pipeline.browser = SimpleNamespace(acquire=acquire)
    with pytest.raises(RunnerFailure):
        await BrowserLayer().resolve(source, source.run_context)
    fetch.assert_awaited_once_with(
        "douyin", source.workspace.path.name, source.run_context.deadline
    )
    assert acquire.call_args.kwargs["ctx"].identity is material
    source.workspace.cleanup()


async def test_layer_cancel_destroys_before_return_and_detaches_listener(tmp_path):
    service = MediaRunnerService(settings(tmp_path))
    source = source_for(service, tmp_path)
    source = replace(
        source, request=provider_request("https://www.douyin.com/video/123")
    )
    ready = asyncio.Event()
    cleaned = asyncio.Event()
    allow = asyncio.Event()
    page = SimpleNamespace(remove_listener=Mock())

    async def navigate(_):
        ready.set()
        await asyncio.Event().wait()

    async def abort():
        cleaned.set()
        await allow.wait()

    operation = SimpleNamespace(page=page, navigate=navigate, abort=abort)
    source.pipeline.browser = SimpleNamespace(acquire=AsyncMock(return_value=operation))
    task = asyncio.create_task(BrowserLayer().resolve(source, source.run_context))
    await ready.wait()
    task.cancel()
    await cleaned.wait()
    assert not task.done()
    allow.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    source.workspace.cleanup()


async def test_browser_native_transfer_saves_before_completion(tmp_path):
    from contextlib import asynccontextmanager

    from app.workers.runner.browser_runtime import BrowserOperation

    output = tmp_path / "media.mp4"
    save_started, save_allowed = asyncio.Event(), asyncio.Event()

    async def save_as(path):
        save_started.set()
        await save_allowed.wait()
        Path(path).write_bytes(b"clear-fixture")

    download = SimpleNamespace(save_as=save_as, failure=AsyncMock(return_value=None))
    pending = asyncio.get_running_loop().create_future()
    pending.set_result(download)

    @asynccontextmanager
    async def expect_download():
        yield SimpleNamespace(value=pending)

    page = SimpleNamespace(expect_download=expect_download, evaluate=AsyncMock())
    close = AsyncMock()
    operation = BrowserOperation(SimpleNamespace(), page, "test", close, close, 1024)
    task = asyncio.create_task(operation.download(MEDIA, output))
    await save_started.wait()
    assert not task.done() and not output.exists()
    assert page.evaluate.call_args.args[1] == {"url": MEDIA, "limit": 1024}
    close.assert_not_awaited()
    save_allowed.set()
    await task
    assert output.read_bytes() == b"clear-fixture"
    close.assert_not_awaited()


async def test_browser_does_not_fetch_identity_after_login_evidence(
    tmp_path, monkeypatch
):
    service = MediaRunnerService(settings(tmp_path))
    source = replace(
        source_for(service, tmp_path),
        request=provider_request("https://www.douyin.com/video/123"),
    )
    monkeypatch.setattr(identity, "validate_cookie_file", lambda _: None)
    material = identity.IdentityMaterial(tmp_path / "mock-cookie", "mock-digest")
    fetch = AsyncMock(return_value=material)
    monkeypatch.setattr(identity, "fetch_identity", fetch)
    layer = BrowserLayer()
    attempt = AsyncMock(
        side_effect=[RunnerFailure("login_required"), RunnerFailure("login_required")]
    )
    source.pipeline.browser = SimpleNamespace(acquire=attempt)
    with pytest.raises(RunnerFailure, match="login required"):
        await layer.resolve(source, source.run_context)
    assert attempt.await_count == 1
    fetch.assert_not_awaited()
    assert attempt.call_args.kwargs["ctx"].identity is None
    fetch.reset_mock()
    attempt.side_effect = RunnerFailure("challenge")
    with pytest.raises(RunnerFailure):
        await layer.resolve(source, source.run_context)
    fetch.assert_not_awaited()
    source.workspace.cleanup()


@pytest.mark.parametrize("value", ["bad-duration", None, {}, []])
def test_malformed_detail_returns_structured_failure(value):
    payload = douyin_payload()
    payload["aweme_detail"]["video"]["duration"] = value
    with pytest.raises(RunnerFailure):
        douyin.parse_response(payload)


def test_xhs_rounded_media_seconds_do_not_override_stream_milliseconds():
    payload = xhs_payload()
    video = payload["data"]["items"][0]["note_card"]["video"]
    del video["consumer"]
    video["media"]["duration"] = 8
    video["capa"] = {"duration": 7}
    video["media"]["stream"]["h264"][0]["duration"] = 7338
    assert xiaohongshu.parse_response(payload).duration_seconds == 7.338


def test_xhs_feed_capa_is_seconds_when_stream_duration_is_absent():
    payload = xhs_payload()
    video = payload["data"]["items"][0]["note_card"]["video"]
    del video["consumer"]
    del video["media"]["stream"]["h264"][0]["duration"]
    video["capa"] = {"duration": 13}
    assert xiaohongshu.parse_response(payload).duration_seconds == 13


def test_r3_cases_have_two_independent_public_works_and_verified_time_baselines():
    cases = json.loads(
        (
            Path(__file__).resolve().parents[4]
            / "scripts/fixtures/r3_public_cases.json"
        ).read_text()
    )
    assert len(cases) == 4
    for platform in ("douyin", "xiaohongshu"):
        own = [case for case in cases if case["platform"] == platform]
        assert len(own) == len({case["expected_media_id"] for case in own}) == 2
        for case in own:
            assert case["content_scope"] == "public" and not case["needs_identity"]
            assert case["duration_seconds"] > 0
            assert case["duration_source"]["status"] == "verified"
            assert case["duration_source"]["kind"] == "platform_page_or_api"
            assert case["minimum_spec"]["audio"] is True
    assert all(
        "xsec_token=" in case["url"]
        for case in cases
        if case["platform"] == "xiaohongshu"
    )
