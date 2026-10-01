"""Kuaishou/Weibo own-page responses, scope and exact work matching."""

import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.services.provider_failures import FailureClass
from app.workers.runner.engine.browser import kuaishou, weibo
from app.workers.runner.engine.browser.intercept import PageResponses
from app.workers.runner.engine.layers.browser import _expected_id
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import provider_request
from test_kuaishou_public_extractor import VIDEO_ID, public_state

MEDIA = "https://media.example.org/video.mp4"


def status():
    return {
        "id": "123",
        "mblogid": "Abc",
        "visible": {"type": 0},
        "page_info": {
            "media_info": {
                "duration": 12,
                "video_title": "公开微博",
                "playback_list": [
                    {
                        "play_info": {
                            "url": MEDIA,
                            "width": 1280,
                            "height": 720,
                            "video_codecs": "h264",
                            "audio_codecs": "aac",
                            "label": "720p",
                            "fps": 30,
                            "mime": "video/mp4",
                        }
                    }
                ],
            }
        },
    }


@pytest.mark.parametrize(
    "payload,work,duration",
    [
        (public_state(), VIDEO_ID, 72.533),
        (
            {
                "data": {
                    "visionVideoDetail": {
                        "photo": {
                            "id": VIDEO_ID,
                            "photoUrl": MEDIA,
                            "durationMs": 12000,
                            "width": 1280,
                            "height": 720,
                        }
                    }
                }
            },
            VIDEO_ID,
            12,
        ),
    ],
)
def test_kuaishou_mobile_and_graphql(payload, work, duration):
    result = kuaishou.parse_response(payload, work)
    assert result.provider_media_id == work and result.duration_seconds == duration
    assert result.download_info["formats"]
    assert result.client == "kuaishou:browser"
    with pytest.raises(RunnerFailure):
        kuaishou.parse_response(payload, "other")


def test_weibo_page_response_preserves_canonical_id():
    result = weibo.parse_response(status(), "Abc")
    assert result.provider_media_id == "123" and result.duration_seconds == 12
    assert result.download_info["formats"][0]["url"] == MEDIA
    with pytest.raises(RunnerFailure):
        weibo.parse_response(status(), "different")


@pytest.mark.parametrize(
    "parser,payload", [(kuaishou, public_state()), (weibo, status())]
)
@pytest.mark.parametrize(
    "flag,kind",
    [
        ("is_private", FailureClass.CONTENT_UNAVAILABLE),
        ("is_paid", FailureClass.CONTENT_UNAVAILABLE),
        ("has_drm", FailureClass.CONTENT_PROTECTED),
    ],
)
def test_g2_does_not_expand_public_content(parser, payload, flag, kind):
    payload = copy.deepcopy(payload)
    if parser is kuaishou:
        payload["opaque-state-key"]["photo"][flag] = True
    else:
        payload[flag] = True
    with pytest.raises(RunnerFailure) as caught:
        parser.parse_response(payload, VIDEO_ID if parser is kuaishou else "123")
    assert caught.value.failure.failure_class is kind


def test_weibo_follower_visibility_stops():
    payload = status()
    payload["visible"]["type"] = 6
    with pytest.raises(RunnerFailure) as caught:
        weibo.parse_response(payload, "123")
    assert caught.value.failure.failure_class is FailureClass.CONTENT_UNAVAILABLE


@pytest.mark.parametrize(
    "site,url,work",
    [
        ("kuaishou", f"https://v.m.chenzhongtech.com/fw/photo/{VIDEO_ID}", VIDEO_ID),
        ("kuaishou", "https://v.kuaishou.com/short", None),
        ("weibo", "https://weibo.com/123/Abc", "Abc"),
    ],
)
def test_platform_work_identity_and_registry(site, url, work):
    assert _expected_id(url, site) == work
    assert provider_request(url).profile.l3_rules.response_patterns


@pytest.mark.parametrize(
    "host,accepted",
    [
        ("www.kuaishou.com", True),
        ("v.m.chenzhongtech.com", True),
        ("evilchenzhongtech.com", False),
        ("kuaishou.com.evil.example", False),
    ],
)
async def test_kuaishou_interception_scope(host, accepted):
    page = SimpleNamespace(on=lambda *args: None, remove_listener=lambda *args: None)
    collector = PageResponses(page, "kuaishou", kuaishou.RULES.response_patterns)
    body = AsyncMock(return_value=json.dumps(public_state()).encode())
    collector._response(
        SimpleNamespace(
            url=f"https://{host}/graphql", status=200, headers={}, body=body
        )
    )
    await asyncio.gather(*collector.tasks)
    assert body.await_count == int(accepted)
    await collector.close()
