"""First-party UPS provenance and full, unencrypted playlist regression."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from app.services.provider_failures import FailureClass
from app.workers.runner.engine.browser import youku
from app.workers.runner.engine.browser.intercept import PageResponses
from app.workers.runner.engine.layers.browser import _expected_id
from app.workers.runner.errors import RunnerFailure

WORK = "XOTUxMzg4NDMy"
URL = "https://cdn.youku.com/full.m3u8"
MANIFEST = "#EXTM3U\n#EXT-X-TARGETDURATION:30\n#EXTINF:30,\npart.ts\n#EXT-X-ENDLIST\n"


def ups():
    return {
        "_framefetch_requested_id": WORK,
        "data": {
            "video": {"title": "Synthetic full video", "seconds": 30},
            "stream": [
                {
                    "drm_type": 0,
                    "m3u8_url": URL,
                    "width": 640,
                    "height": 360,
                    "milliseconds_video": 30000,
                    "segs": [{"cdn_url": "https://cdn.youku.com/part.ts"}],
                }
            ],
        },
    }


def test_official_player_response_keeps_work_and_full_duration():
    result = youku.parse_response(ups(), WORK)
    assert result.provider_media_id == WORK
    assert result.duration_seconds == 30
    assert result.client == "youku:browser"
    assert result.download_info["_framefetch_full_stream"] is True
    assert result.download_info["formats"][0]["url"] == URL
    assert _expected_id(f"https://v.youku.com/v_show/id_{WORK}==.html", "youku") == WORK


@pytest.mark.parametrize(
    "change,reason",
    [
        (lambda x: x.pop("_framefetch_requested_id"), "work_identity_mismatch"),
        (
            lambda x: x.update(_framefetch_requested_id="other"),
            "work_identity_mismatch",
        ),
        (
            lambda x: x["data"]["stream"][0].update(milliseconds_video=5000),
            "full_media_unproven",
        ),
        (lambda x: x["data"]["stream"][0]["segs"].append({}), "full_media_unproven"),
        (lambda x: x["data"]["stream"][0].update(drm_type=1), "clear_media_missing"),
    ],
)
def test_wrong_asset_preview_and_encrypted_stream_never_expose_formats(change, reason):
    data = ups()
    change(data)
    with pytest.raises(RunnerFailure) as error:
        youku.parse_response(data, WORK)
    assert error.value.failure.evidence["cause_code"] == reason


@pytest.mark.parametrize(
    "error,expected",
    [
        ({"code": -6004, "note": "ccode rejected"}, FailureClass.CHALLENGE),
        ({"note": "该视频被设为私密"}, FailureClass.CONTENT_UNAVAILABLE),
        ({"note": "该视频有 DRM 保护"}, FailureClass.CONTENT_PROTECTED),
        (
            {"note": "由于版权原因，您所在地区无法播放"},
            FailureClass.CONTENT_UNAVAILABLE,
        ),
        ({"note": "drm protected"}, FailureClass.CONTENT_PROTECTED),
    ],
)
def test_ups_restrictions_are_structured_without_raw_account_response(error, expected):
    data = ups()
    data["data"]["error"] = error
    with pytest.raises(RunnerFailure) as caught:
        youku.parse_response(data, WORK)
    assert caught.value.failure.failure_class is expected
    assert "ccode rejected" not in str(caught.value.failure.evidence)


def test_clear_full_manifest_rebases_segment_without_requesting_key():
    playlist, first = youku.clear_manifest(MANIFEST, URL, 30)
    assert first == "https://cdn.youku.com/part.ts"
    assert first in playlist


def test_ups_default_rendition_still_requires_clear_manifest():
    payload = ups()
    payload["data"]["stream"][0]["drm_type"] = "default"
    assert youku.parse_response(payload, WORK).streams == ()
    with pytest.raises(RunnerFailure) as caught:
        youku.clear_manifest(
            MANIFEST.replace("#EXTINF:", "#EXT-X-KEY:METHOD=AES-128\n#EXTINF:"),
            URL,
            30,
        )
    assert caught.value.failure.failure_class is FailureClass.CONTENT_PROTECTED


@pytest.mark.parametrize(
    "manifest,reason",
    [
        (
            MANIFEST.replace(
                "#EXTINF:",
                '#EXT-X-KEY:METHOD=AES-128,URI="https://cdn.youku.com/key"\n#EXTINF:',
            ),
            "encrypted_playlist",
        ),
        (
            MANIFEST.replace(
                "#EXTINF:", "#EXT-X-SESSION-KEY:METHOD=SAMPLE-AES\n#EXTINF:"
            ),
            "encrypted_playlist",
        ),
        (MANIFEST.replace("#EXTINF:30", "#EXTINF:5"), "preview_playlist"),
        (MANIFEST.replace("#EXT-X-ENDLIST", ""), "full_playlist_unproven"),
        (MANIFEST.replace("part.ts", "http://127.0.0.1/key"), "invalid_url"),
        (MANIFEST.replace("#EXTINF:30,\n", ""), "invalid_playlist"),
        (MANIFEST.replace("part.ts", "#EXTINF:30,\npart.ts"), "invalid_playlist"),
    ],
)
def test_protected_partial_and_private_network_playlists_rejected(manifest, reason):
    with pytest.raises(RunnerFailure) as caught:
        youku.clear_manifest(manifest, URL, 30)
    assert (
        caught.value.failure.evidence.get("cause_code") == reason
        or caught.value.code == reason
    )


async def test_collector_binds_only_exact_first_party_ups_request():
    import json

    page = Mock()
    collector = PageResponses(page, "youku", youku.RULES.response_patterns)

    def response(url):
        return SimpleNamespace(
            url=url,
            status=200,
            headers={"content-type": "application/json"},
            body=AsyncMock(
                return_value=json.dumps(
                    {"_framefetch_requested_id": "spoofed", "data": ups()["data"]}
                ).encode()
            ),
        )

    for url in [
        "https://ups.youku.com.evil/ups/get.json?vid=" + WORK,
        "https://www.youku.com/ups/get.json?vid=" + WORK,
        "https://ups.youku.com/ups/get.json/other?vid=" + WORK,
    ]:
        collector._response(response(url))
    assert not collector.tasks
    collector._response(
        response("https://ups.youku.com/ups/get.json?vid=" + WORK + "==")
    )
    await asyncio.gather(*tuple(collector.tasks))
    payload = collector.queue.get_nowait()
    assert payload["_framefetch_requested_id"] == WORK
    assert youku.parse_response(payload, WORK).provider_media_id == WORK
    await collector.close()


@pytest.mark.parametrize("encrypted", [True, False])
async def test_manifest_read_is_bounded_and_never_fetches_keys(monkeypatch, encrypted):
    import httpx

    requested = []

    def respond(request):
        requested.append(str(request.url))
        assert "cookie" not in request.headers
        body = (
            MANIFEST.replace(
                "#EXTINF:", '#EXT-X-KEY:METHOD=AES-128,URI="key"\n#EXTINF:'
            )
            if encrypted
            else MANIFEST
        )
        return httpx.Response(200, text=body)

    client_type = httpx.AsyncClient

    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return client_type(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(youku.httpx, "AsyncClient", client)
    ctx = SimpleNamespace(
        egress=SimpleNamespace(proxy_url=None),
        user_agent="test",
        referer="https://v.youku.com/",
    )
    resolved = youku.parse_response(ups(), WORK)
    if encrypted:
        with pytest.raises(RunnerFailure) as caught:
            await youku.prepare_manifests(resolved, ctx)
        assert caught.value.failure.failure_class is FailureClass.CONTENT_PROTECTED
    else:
        await youku.prepare_manifests(resolved, ctx)
        raw = resolved.download_info["formats"][0]
        assert raw["_framefetch_probe_url"] == "https://cdn.youku.com/part.ts"
        assert raw["hls_media_playlist_data"].endswith("#EXT-X-ENDLIST\n")
    assert requested == [URL]


@pytest.mark.parametrize(
    "tag",
    [
        '#EXT-X-KEY=METHOD=AES-128,URI="https://cdn.youku.com/key"',
        '#EXT-X-KEY METHOD=AES-128,URI="https://cdn.youku.com/key"',
        '#ext-x-key:METHOD=AES-128,URI="https://cdn.youku.com/key"',
        '#EXT-X-SESSION-KEY=METHOD=SAMPLE-AES,URI="https://cdn.youku.com/key"',
    ],
)
async def test_malformed_key_rejected_before_segment_or_key_request(monkeypatch, tag):
    import httpx

    requested = []

    def respond(request):
        requested.append(str(request.url))
        assert str(request.url) == URL
        return httpx.Response(
            200, text=MANIFEST.replace("#EXTINF:", tag + "\n#EXTINF:")
        )

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        youku.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    ctx = SimpleNamespace(
        egress=SimpleNamespace(proxy_url=None),
        user_agent="test",
        referer="https://v.youku.com/",
    )
    with pytest.raises(RunnerFailure) as caught:
        await youku.prepare_manifests(youku.parse_response(ups(), WORK), ctx)
    assert caught.value.failure.failure_class is FailureClass.CONTENT_PROTECTED
    assert caught.value.failure.evidence["cause_code"] == "encrypted_playlist"
    assert requested == [URL]


@pytest.mark.parametrize("mode", ["large", "redirect", "network"])
async def test_manifest_size_redirect_and_network_limits(monkeypatch, mode):
    import httpx

    def respond(request):
        if mode == "network":
            raise httpx.ConnectError("private upstream detail", request=request)
        if mode == "redirect":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/key"})
        return httpx.Response(200, content=b"x" * (youku.MAX_MANIFEST_BYTES + 1))

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        youku.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    ctx = SimpleNamespace(
        egress=SimpleNamespace(proxy_url=None),
        user_agent="test",
        referer="https://v.youku.com/",
    )
    with pytest.raises(RunnerFailure) as caught:
        await youku.prepare_manifests(youku.parse_response(ups(), WORK), ctx)
    assert (
        caught.value.failure.failure_class
        is {
            "large": FailureClass.FORMAT_UNAVAILABLE,
            "redirect": FailureClass.CHALLENGE,
            "network": FailureClass.NETWORK_BLOCKED,
        }[mode]
    )
    assert "private upstream detail" not in str(caught.value.failure.evidence)


async def test_youku_layer_probes_clear_segment_and_owns_handoff(tmp_path, monkeypatch):
    from app.workers.runner.engine import identity
    from app.workers.runner.engine.layers import browser
    from app.workers.runner.provider_registry import provider_request
    from app.workers.runner.service import MediaRunnerService
    from helpers import settings
    from test_engine_skeleton import source_for

    monkeypatch.setattr(identity, "COOKIE_TMPFS_ROOT", tmp_path / "private")
    monkeypatch.setattr(identity, "validate_cookie_file", lambda _: None)
    jar = tmp_path / "synthetic-identity"
    jar.write_text("synthetic")
    material = identity.IdentityMaterial(jar, "synthetic-digest")
    monkeypatch.setattr(identity, "fetch_identity", AsyncMock(return_value=material))
    service = MediaRunnerService(settings(tmp_path))
    source = source_for(service, tmp_path)
    source = replace(
        source,
        request=provider_request(f"https://v.youku.com/v_show/id_{WORK}.html"),
    )
    previous = tmp_path / "private" / "http-mutated" / "cookies.txt"
    previous.parent.mkdir(parents=True)
    previous.write_text("out-of-scope visitor cookie")
    source = replace(
        source,
        run_context=source.run_context.with_material(
            identity=identity.IdentityMaterial(previous, "previous-digest"),
        ),
    )
    page = SimpleNamespace(
        url=source.request.source_url,
        wait_for_timeout=AsyncMock(),
        evaluate=AsyncMock(return_value="null"),
        close=AsyncMock(),
    )
    operation = SimpleNamespace(
        page=page,
        navigate=AsyncMock(),
        user_agent="browser-UA",
        cookies=AsyncMock(return_value=[]),
        abort=AsyncMock(),
        close=AsyncMock(),
    )
    queue = asyncio.Queue()
    queue.put_nowait(ups())
    monkeypatch.setattr(
        browser,
        "PageResponses",
        lambda *args: SimpleNamespace(start=Mock(), queue=queue, close=AsyncMock()),
    )
    source.pipeline.browser = SimpleNamespace(acquire=AsyncMock(return_value=operation))

    async def manifest(resolved, ctx):
        assert ctx.identity.digest == "synthetic-digest"
        resolved.download_info["formats"][0]["_framefetch_probe_url"] = (
            "https://cdn.youku.com/part.ts"
        )

    monkeypatch.setattr(youku, "prepare_manifests", manifest)
    source.pipeline._commands.probe_remote_prefix = AsyncMock(
        return_value={
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 640,
                    "height": 360,
                    "avg_frame_rate": "25/1",
                },
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        }
    )
    result = await browser.BrowserLayer().resolve(source, source.run_context)
    assert not previous.parent.exists()
    assert result.streams and result.duration_seconds == 30
    assert result.download_info["formats"][0]["vcodec"] == "h264"
    assert (
        source.pipeline._commands.probe_remote_prefix.call_args.args[0]
        == "https://cdn.youku.com/part.ts"
    )
    assert result.run_context.identity.digest == "synthetic-digest"
    await result.run_context.browser.close()
    operation.close.assert_awaited_once()
    operation.abort.assert_not_awaited()
    assert not result.run_context.cookie_file.parent.exists()
    source.workspace.cleanup()
