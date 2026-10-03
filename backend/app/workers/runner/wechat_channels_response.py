"""Pure decoding of captured Yuanbao and official feed response structures.

The reference records the supplied request context. It does not verify work
identity, media rights, availability or original full duration. This module
performs no requests or account operations.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, TypeGuard
from urllib.parse import SplitResult, parse_qs, urlsplit

from app.workers.runner.url_policy import UrlPolicyError, validate_media_url

_PARSE_HOST = "yuanbao.tencent.com"
_PARSE_PATH = "/api/weixin/get_parse_result"
_REFERENCE_HOST = "channels.weixin.qq.com"
_REFERENCE_PATH = "/finder-preview/pages/feed"
_FEED_PATH = "/finder-preview/api/feed/get_feed_info"
_SHARE_URL = re.compile(r"https://weixin\.qq\.com/sph/[A-Za-z0-9_-]{4,256}")
_BAD_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_REFERENCE_TICKETS = frozenset({"token", "eid"})
_PRESENTATION_FIELDS = frozenset(
    {"entry_card_type", "comment_scene", "appid", "entry_scene"}
)
_PRESENTATION_NUMBER = re.compile(r"[0-9]{1,10}")
_MAX_PRESENTATION_VALUE = 2**31 - 1


@dataclass(frozen=True, slots=True)
class YuanbaoReference:
    """Request reference whose export_id is the once-decoded URL eid ticket."""

    canonical_share_url: str
    token: str = field(repr=False)
    export_id: str = field(repr=False)


def successful_response_data(
    payload: object, code_field: Literal["code", "errCode"]
) -> Mapping[str, Any]:
    if code_field not in ("code", "errCode") or not isinstance(payload, Mapping):
        return {}
    code = payload.get(code_field)
    if not (type(code) is int and code == 0 or isinstance(code, str) and code == "0"):
        return {}
    data = payload.get("data")
    return data if isinstance(data, Mapping) else {}


def yuanbao_reference(
    *,
    request_method: object,
    request_url: object,
    response_url: object,
    http_status: object,
    request_body: object,
    canonical_share_url: object,
    payload: object,
) -> YuanbaoReference | None:
    """Decode a bound request reference, not work identity, rights or duration.

    Query tickets are decoded once. Optional presentation fields are discarded;
    wx_export_id has separate semantics and never supplies the feed eid ticket.
    """
    if (
        not _captured_post_matches(
            request_method,
            request_url,
            response_url,
            http_status,
            _PARSE_HOST,
            _PARSE_PATH,
        )
        or not isinstance(canonical_share_url, str)
        or _SHARE_URL.fullmatch(canonical_share_url) is None
        or not isinstance(request_body, Mapping)
        or len(request_body) != 3
        or set(request_body) != {"type", "url", "scene"}
        or request_body.get("type") != "video_channel_url"
        or request_body.get("url") != canonical_share_url
        or type(request_body.get("scene")) is not int
        or request_body.get("scene") != 1
    ):
        return None
    data = successful_response_data(payload, "code")
    aliases = [data[name] for name in ("playable_url", "playableUrl") if name in data]
    if (
        not aliases
        or any(not isinstance(value, str) for value in aliases)
        or any(value != aliases[0] for value in aliases[1:])
    ):
        return None
    reference = _official_url(aliases[0], _REFERENCE_HOST, _REFERENCE_PATH)
    if reference is None or _BAD_ESCAPE.search(reference.query):
        return None
    try:
        query = parse_qs(
            reference.query,
            keep_blank_values=True,
            strict_parsing=True,
            errors="strict",
            max_num_fields=len(_REFERENCE_TICKETS | _PRESENTATION_FIELDS),
        )
    except (UnicodeError, ValueError):
        return None
    if (
        not _REFERENCE_TICKETS <= query.keys()
        or not query.keys() <= _REFERENCE_TICKETS | _PRESENTATION_FIELDS
        or any(len(values) != 1 for values in query.values())
        or any(
            _PRESENTATION_NUMBER.fullmatch(query[name][0]) is None
            or int(query[name][0]) > _MAX_PRESENTATION_VALUE
            for name in query.keys() & _PRESENTATION_FIELDS
        )
    ):
        return None
    token, export_id = query["token"][0], query["eid"][0]
    if not _safe_text(token, 2048) or not _safe_text(export_id, 512):
        return None
    if "wx_export_id" in data:
        observed_id = data["wx_export_id"]
        if not isinstance(observed_id, str) or not _safe_text(observed_id, 512):
            return None
    return YuanbaoReference(canonical_share_url, token, export_id)


def authenticated_feed_info(
    *,
    request_method: object,
    request_url: object,
    response_url: object,
    http_status: object,
    request_body: object,
    reference: object,
    payload: object,
) -> Mapping[str, Any] | None:
    """Return captured feed metadata bound to the caller's reference context.

    This checks the once-decoded URL request tickets. It does not establish a
    response work-id echo, media rights, availability or original full duration.
    """
    if (
        not _valid_reference(reference)
        or not _captured_post_matches(
            request_method,
            request_url,
            response_url,
            http_status,
            _REFERENCE_HOST,
            _FEED_PATH,
        )
        or not isinstance(request_body, Mapping)
        or len(request_body) != 2
        or set(request_body) != {"baseReq", "exportId"}
        or request_body.get("exportId") != reference.export_id
    ):
        return None
    base = request_body.get("baseReq")
    if (
        not isinstance(base, Mapping)
        or len(base) != 1
        or set(base) != {"generalToken"}
        or base.get("generalToken") != reference.token
    ):
        return None
    data = successful_response_data(payload, "errCode")
    feed = data.get("feedInfo")
    return feed if isinstance(feed, Mapping) and feed else None


def _valid_reference(value: object) -> TypeGuard[YuanbaoReference]:
    return (
        isinstance(value, YuanbaoReference)
        and isinstance(value.canonical_share_url, str)
        and _SHARE_URL.fullmatch(value.canonical_share_url) is not None
        and isinstance(value.token, str)
        and _safe_text(value.token, 2048)
        and isinstance(value.export_id, str)
        and _safe_text(value.export_id, 512)
    )


def _captured_post_matches(
    method: object,
    request_url: object,
    response_url: object,
    http_status: object,
    host: str,
    path: str,
) -> bool:
    return (
        method == "POST"
        and _official_url(request_url, host, path) is not None
        and _official_url(response_url, host, path) is not None
        and "?" not in str(request_url)
        and "?" not in str(response_url)
        and isinstance(http_status, int)
        and not isinstance(http_status, bool)
        and 200 <= http_status < 300
    )


def _official_url(value: object, host: str, path: str) -> SplitResult | None:
    if not isinstance(value, str) or not _safe_text(value, 4096) or "#" in value:
        return None
    try:
        validated = validate_media_url(value)
        parsed = urlsplit(validated.value)
    except UrlPolicyError:
        return None
    if validated.scheme != "https" or parsed.hostname != host or parsed.path != path:
        return None
    return parsed


def _safe_text(value: str, max_length: int) -> bool:
    if not value or len(value) > max_length:
        return False
    if any(
        character.isspace() or unicodedata.category(character) in {"Cc", "Cf", "Cs"}
        for character in value
    ):
        return False
    return True
