from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from typing import Literal

import pytest
from app.workers.runner.wechat_channels_response import (
    YuanbaoReference,
    authenticated_feed_info,
    successful_response_data,
    yuanbao_reference,
)

PARSE_URL = "https://yuanbao.tencent.com/api/weixin/get_parse_result"
SHARE_URL = "https://weixin.qq.com/sph/SyntheticShare"
FEED_URL = "https://channels.weixin.qq.com/finder-preview/pages/feed"
TOKEN = "synthetic-token"
EXPORT_ID = "synthetic-export"
REFERENCE_URL = f"{FEED_URL}?token={TOKEN}&eid={EXPORT_ID}"


def captured_reference(**overrides: object) -> YuanbaoReference | None:
    arguments: dict[str, object] = {
        "request_method": "POST",
        "request_url": PARSE_URL,
        "response_url": PARSE_URL,
        "http_status": 200,
        "request_body": {"type": "video_channel_url", "url": SHARE_URL, "scene": 1},
        "canonical_share_url": SHARE_URL,
        "payload": {"code": 0, "data": {"playable_url": REFERENCE_URL}},
    }
    arguments.update(overrides)
    return yuanbao_reference(**arguments)


@pytest.mark.parametrize("code_field", ["code", "errCode"])
@pytest.mark.parametrize("code", [0, "0"])
def test_successful_response_preserves_only_the_matching_data_mapping(
    code_field: Literal["code", "errCode"], code: object
) -> None:
    data = {"synthetic": "metadata"}
    assert (
        successful_response_data({code_field: code, "data": data}, code_field) is data
    )


@pytest.mark.parametrize("code_field", ["code", "errCode"])
@pytest.mark.parametrize("code", [False, True, 0.0, None, "", " 0", "00", -1, "1"])
def test_invalid_success_code_does_not_release_data(
    code_field: Literal["code", "errCode"], code: object
) -> None:
    assert (
        successful_response_data(
            {code_field: code, "data": {"synthetic": True}}, code_field
        )
        == {}
    )


@pytest.mark.parametrize(
    "payload", [None, [], {}, {"code": 0}, {"code": 0, "data": []}]
)
def test_successful_response_requires_an_envelope_and_data_mapping(
    payload: object,
) -> None:
    assert successful_response_data(payload, "code") == {}


def test_successful_response_does_not_substitute_another_code_field() -> None:
    assert (
        successful_response_data({"errCode": 0, "data": {"synthetic": True}}, "code")
        == {}
    )
    assert (
        successful_response_data({"code": 0, "data": {"synthetic": True}}, "errCode")
        == {}
    )


def test_captured_reference_is_immutable_and_keeps_tickets_out_of_repr() -> None:
    reference = captured_reference()
    assert reference is not None
    assert reference.canonical_share_url == SHARE_URL
    assert reference.token == TOKEN
    assert reference.export_id == EXPORT_ID
    assert TOKEN not in repr(reference)
    assert EXPORT_ID not in repr(reference)
    assert not hasattr(reference, "duration")
    assert not hasattr(reference, "availability")
    with pytest.raises(FrozenInstanceError):
        reference.token = "replacement"  # type: ignore[misc]


@pytest.mark.parametrize("code", [0, "0"])
@pytest.mark.parametrize("alias", ["playable_url", "playableUrl"])
def test_historical_reference_aliases_and_success_codes_are_decoded(
    code: object, alias: str
) -> None:
    reference = captured_reference(
        payload={"code": code, "data": {alias: REFERENCE_URL}}
    )
    assert reference is not None
    assert reference.export_id == EXPORT_ID


def test_identical_reference_aliases_are_unambiguous() -> None:
    assert (
        captured_reference(
            payload={
                "code": 0,
                "data": {"playable_url": REFERENCE_URL, "playableUrl": REFERENCE_URL},
            }
        )
        is not None
    )


def test_reference_values_are_url_decoded_once_without_constructing_requests() -> None:
    reference = captured_reference(
        payload={
            "code": 0,
            "data": {
                "playable_url": (
                    f"{FEED_URL}?eid=synthetic%2Fexport&token=synthetic%2Btoken"
                )
            },
        }
    )
    assert reference is not None
    assert reference.token == "synthetic+token"
    assert reference.export_id == "synthetic/export"


@pytest.mark.parametrize("field", ["request_url", "response_url"])
@pytest.mark.parametrize(
    "url",
    [
        None,
        "http://yuanbao.tencent.com/api/weixin/get_parse_result",
        "https://yuanbao.tencent.com.evil.test/api/weixin/get_parse_result",
        "https://channels.weixin.qq.com/api/weixin/get_parse_result",
        f"{PARSE_URL}/",
        f"{PARSE_URL}?",
        f"{PARSE_URL}?other=synthetic",
        f"{PARSE_URL}#",
        "https://synthetic@yuanbao.tencent.com/api/weixin/get_parse_result",
        "https://yuanbao.tencent.com:invalid/api/weixin/get_parse_result",
        "https://yuanbao.tencent.com:65536/api/weixin/get_parse_result",
        "https://yuanbao.tencent.com:444/api/weixin/get_parse_result",
        "https://yuanbao.tencent.com./api/weixin/get_parse_result",
        "https://yuanbao.tencent.com/api/weixin/get_parse_\nresult",
        "https://yuanbao.tencent.com/api/weixin/get_parse_result\u200b",
    ],
)
def test_reference_rejects_cross_origin_or_ambiguous_transport_urls(
    field: str, url: object
) -> None:
    assert captured_reference(**{field: url}) is None


def test_transport_accepts_explicit_standard_https_ports() -> None:
    assert (
        captured_reference(
            request_url=PARSE_URL.replace(
                "yuanbao.tencent.com", "yuanbao.tencent.com:443"
            ),
            response_url=PARSE_URL.replace(
                "yuanbao.tencent.com", "yuanbao.tencent.com:443"
            ),
        )
        is not None
    )


@pytest.mark.parametrize("method", [None, "", "GET", "PUT", "post", " POST", 1])
def test_reference_requires_the_historical_post_method(method: object) -> None:
    assert captured_reference(request_method=method) is None


@pytest.mark.parametrize("status", [None, True, 200.0, "200", 199, 300, 401, 500])
def test_reference_requires_a_successful_integer_http_status(status: object) -> None:
    assert captured_reference(http_status=status) is None


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"type": "article_url", "url": SHARE_URL, "scene": 1},
        {
            "type": "video_channel_url",
            "url": "https://weixin.qq.com/sph/OtherShare",
            "scene": 1,
        },
        {"type": "video_channel_url", "url": SHARE_URL, "scene": True},
        {"type": "video_channel_url", "url": SHARE_URL, "scene": 1.0},
        {"type": "video_channel_url", "url": SHARE_URL, "scene": "1"},
        {"type": "video_channel_url", "url": SHARE_URL, "scene": 2},
        {
            "type": "video_channel_url",
            "url": SHARE_URL,
            "scene": 1,
            "other": "synthetic",
        },
    ],
)
def test_reference_requires_the_exact_historical_request_context(body: object) -> None:
    assert captured_reference(request_body=body) is None


@pytest.mark.parametrize(
    "share_url",
    [
        None,
        "http://weixin.qq.com/sph/SyntheticShare",
        "https://weixin.qq.com:443/sph/SyntheticShare",
        "https://weixin.qq.com/sph/abc",
        f"{SHARE_URL}/",
        f"{SHARE_URL}?tracking=synthetic",
        f"{SHARE_URL}#fragment",
        "https://weixin.qq.com.evil.test/sph/SyntheticShare",
        "https://channels.weixin.qq.com/finder-preview/pages/sph?id=SyntheticShare",
    ],
)
def test_reference_does_not_normalize_noncanonical_share_inputs(
    share_url: object,
) -> None:
    assert (
        captured_reference(
            canonical_share_url=share_url,
            request_body={"type": "video_channel_url", "url": share_url, "scene": 1},
        )
        is None
    )


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"playable_url": None},
        {"playable_url": 1},
        {"playable_url": ""},
        {
            "playable_url": REFERENCE_URL,
            "playableUrl": f"{FEED_URL}?token=other&eid=other",
        },
        {"playable_url": "", "playableUrl": REFERENCE_URL},
    ],
)
def test_missing_invalid_or_conflicting_reference_fields_fail_closed(
    data: object,
) -> None:
    assert captured_reference(payload={"code": 0, "data": data}) is None


@pytest.mark.parametrize(
    "reference_url",
    [
        REFERENCE_URL.replace("https:", "http:"),
        REFERENCE_URL.replace(
            "channels.weixin.qq.com", "channels.weixin.qq.com.evil.test"
        ),
        REFERENCE_URL.replace(
            "channels.weixin.qq.com", "synthetic@channels.weixin.qq.com"
        ),
        REFERENCE_URL.replace(
            "channels.weixin.qq.com", "channels.weixin.qq.com:invalid"
        ),
        REFERENCE_URL.replace("channels.weixin.qq.com", "channels.weixin.qq.com:65536"),
        REFERENCE_URL.replace("/pages/feed", "/pages/sph"),
        f"{REFERENCE_URL}#",
        f"{FEED_URL}?token=&eid=synthetic",
        f"{FEED_URL}?token=synthetic&eid=",
        f"{FEED_URL}?token=synthetic",
        f"{FEED_URL}?token=synthetic&eid=synthetic&token=",
        f"{FEED_URL}?token=synthetic&eid=synthetic&eid=other",
        f"{REFERENCE_URL}&extra=synthetic",
        f"{REFERENCE_URL}&broken",
        f"{FEED_URL}?token=%&eid=synthetic",
        f"{FEED_URL}?token=%GG&eid=synthetic",
        f"{FEED_URL}?token=%FF&eid=synthetic",
        f"{FEED_URL}?token=%C3%28&eid=synthetic",
        f"{FEED_URL}?token=synthetic%00&eid=synthetic",
        f"{FEED_URL}?token=synthetic%7F&eid=synthetic",
        f"{FEED_URL}?token=synthetic%20token&eid=synthetic",
        f"{FEED_URL}?token=synthetic+token&eid=synthetic",
        f"{FEED_URL}?token=synthetic%E2%80%8Btoken&eid=synthetic",
        pytest.param(
            f"{FEED_URL}?token={'a' * 2049}&eid=synthetic", id="token-too-long"
        ),
        pytest.param(
            f"{FEED_URL}?token=synthetic&eid={'a' * 513}", id="export-id-too-long"
        ),
        pytest.param(f"{FEED_URL}?token={'a' * 4096}&eid=synthetic", id="url-too-long"),
    ],
)
def test_reference_rejects_unsafe_tickets_and_unsupported_urls(
    reference_url: str,
) -> None:
    assert (
        captured_reference(payload={"code": 0, "data": {"playable_url": reference_url}})
        is None
    )


def test_adapter_does_not_modify_the_capture() -> None:
    payload = {"code": 0, "data": {"playable_url": REFERENCE_URL}}
    original = deepcopy(payload)
    assert captured_reference(payload=payload) is not None
    assert payload == original


@pytest.mark.parametrize(
    "export_id",
    [
        None,
        False,
        1,
        "",
        "other-synthetic-export",
        "synthetic-export\x00",
        "synthetic-export\u0080",
        "synthetic-export\u200b",
        "synthetic-export\ud800",
        pytest.param("x" * 513, id="export-field-too-long"),
    ],
)
def test_reference_rejects_an_invalid_or_conflicting_export_field(
    export_id: object,
) -> None:
    assert (
        captured_reference(
            payload={
                "code": 0,
                "data": {"playable_url": REFERENCE_URL, "wx_export_id": export_id},
            }
        )
        is None
    )


def test_reference_checks_the_export_field_against_the_decoded_eid() -> None:
    reference = captured_reference(
        payload={
            "code": 0,
            "data": {
                "playable_url": f"{FEED_URL}?token=synthetic&eid=synthetic%2Fexport",
                "wx_export_id": "synthetic/export",
            },
        }
    )

    assert reference is not None
    assert reference.export_id == "synthetic/export"


FEED_API_URL = "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"
CAPTURED_FEED = {"description": "Synthetic public video", "objectId": "synthetic-work"}


def captured_feed(**overrides: object) -> object:
    arguments: dict[str, object] = {
        "request_method": "POST",
        "request_url": FEED_API_URL,
        "response_url": FEED_API_URL,
        "http_status": 200,
        "request_body": {
            "baseReq": {"generalToken": TOKEN},
            "exportId": EXPORT_ID,
        },
        "reference": captured_reference(),
        "payload": {"errCode": 0, "data": {"feedInfo": CAPTURED_FEED}},
    }
    arguments.update(overrides)
    return authenticated_feed_info(**arguments)


@pytest.mark.parametrize("code", [0, "0"])
def test_authenticated_feed_preserves_metadata_for_the_bound_capture(
    code: object,
) -> None:
    feed = deepcopy(CAPTURED_FEED)
    payload = {"errCode": code, "data": {"feedInfo": feed}}
    original = deepcopy(payload)

    assert captured_feed(payload=payload) is feed
    assert payload == original
    assert "duration" not in feed
    assert "availability" not in feed


@pytest.mark.parametrize("method", [None, "", "GET", "PUT", "post", " POST", 1])
def test_authenticated_feed_requires_the_captured_post_method(method: object) -> None:
    assert captured_feed(request_method=method) is None


@pytest.mark.parametrize("field", ["request_url", "response_url"])
@pytest.mark.parametrize(
    "url",
    [
        None,
        FEED_API_URL.replace("https:", "http:"),
        FEED_API_URL.replace("channels.weixin.qq.com", "yuanbao.tencent.com"),
        FEED_API_URL.replace(
            "channels.weixin.qq.com", "channels.weixin.qq.com.evil.test"
        ),
        FEED_API_URL.replace(
            "channels.weixin.qq.com", "synthetic@channels.weixin.qq.com"
        ),
        FEED_API_URL.replace(
            "channels.weixin.qq.com", "channels.weixin.qq.com:invalid"
        ),
        FEED_API_URL.replace("channels.weixin.qq.com", "channels.weixin.qq.com:444"),
        FEED_API_URL.replace("channels.weixin.qq.com", "channels.weixin.qq.com."),
        f"{FEED_API_URL}/",
        f"{FEED_API_URL}?",
        f"{FEED_API_URL}?exportId={EXPORT_ID}",
        f"{FEED_API_URL}#",
        FEED_API_URL.replace("get_feed_info", "get_feed_\ninfo"),
    ],
)
def test_authenticated_feed_rejects_unbound_or_ambiguous_transport(
    field: str, url: object
) -> None:
    assert captured_feed(**{field: url}) is None


def test_authenticated_feed_accepts_the_standard_https_port() -> None:
    url = FEED_API_URL.replace("channels.weixin.qq.com", "channels.weixin.qq.com:443")
    assert captured_feed(request_url=url, response_url=url) is CAPTURED_FEED


@pytest.mark.parametrize("status", [None, True, 200.0, "200", 199, 300, 401, 500])
def test_authenticated_feed_requires_a_successful_integer_http_status(
    status: object,
) -> None:
    assert captured_feed(http_status=status) is None


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"exportId": EXPORT_ID},
        {"baseReq": {"generalToken": TOKEN}},
        {"baseReq": {"generalToken": TOKEN}, "exportId": "other-synthetic-export"},
        {"baseReq": {"generalToken": "other-synthetic-token"}, "exportId": EXPORT_ID},
        {"baseReq": {"generalToken": None}, "exportId": EXPORT_ID},
        {"baseReq": None, "exportId": EXPORT_ID},
        {"baseReq": {}, "exportId": EXPORT_ID},
        {
            "baseReq": {"generalToken": TOKEN, "other": "synthetic"},
            "exportId": EXPORT_ID,
        },
        {
            "baseReq": {"generalToken": TOKEN},
            "exportId": EXPORT_ID,
            "shortUri": "SyntheticShare",
        },
    ],
)
def test_authenticated_feed_requires_both_exact_reference_tickets(body: object) -> None:
    assert captured_feed(request_body=body) is None


@pytest.mark.parametrize(
    "reference",
    [
        None,
        {"canonical_share_url": SHARE_URL, "token": TOKEN, "export_id": EXPORT_ID},
        YuanbaoReference(f"{SHARE_URL}?tracking=synthetic", TOKEN, EXPORT_ID),
        YuanbaoReference(
            "https://weixin.qq.com.evil.test/sph/SyntheticShare", TOKEN, EXPORT_ID
        ),
        YuanbaoReference(SHARE_URL, "", EXPORT_ID),
        YuanbaoReference(SHARE_URL, "synthetic token", EXPORT_ID),
        YuanbaoReference(SHARE_URL, TOKEN, ""),
        YuanbaoReference(SHARE_URL, TOKEN, "synthetic\x00export"),
    ],
)
def test_authenticated_feed_rejects_invalid_reference_objects(
    reference: object,
) -> None:
    assert captured_feed(reference=reference) is None


@pytest.mark.parametrize("code", [False, True, 0.0, None, "", "00", -1, "1"])
def test_authenticated_feed_requires_its_own_explicit_success_code(
    code: object,
) -> None:
    assert (
        captured_feed(payload={"errCode": code, "data": {"feedInfo": CAPTURED_FEED}})
        is None
    )


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"code": 0, "data": {"feedInfo": CAPTURED_FEED}},
        {"errCode": 0},
        {"errCode": 0, "data": []},
        {"errCode": 0, "data": {"feedInfo": None}},
        {"errCode": 0, "data": {"feedInfo": {}}},
        {"errCode": 0, "data": {"feedInfo": [CAPTURED_FEED]}},
        {"errCode": 0, "data": {"data": {"feedInfo": CAPTURED_FEED}}},
        {"errCode": -1, "data": {"errCode": 0, "data": {"feedInfo": CAPTURED_FEED}}},
    ],
)
def test_authenticated_feed_rejects_missing_or_nested_success_packages(
    payload: object,
) -> None:
    assert captured_feed(payload=payload) is None
