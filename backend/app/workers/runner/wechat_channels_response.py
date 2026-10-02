"""Pure decoding of captured historical Yuanbao response structures.

The reference records the supplied request context, not verified work identity
or media availability. This module performs no requests or account operations.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import SplitResult, parse_qs, urlsplit

from app.workers.runner.url_policy import UrlPolicyError, validate_media_url

_PARSE_HOST = "yuanbao.tencent.com"
_PARSE_PATH = "/api/weixin/get_parse_result"
_REFERENCE_HOST = "channels.weixin.qq.com"
_REFERENCE_PATH = "/finder-preview/pages/feed"
_SHARE_URL = re.compile(r"https://weixin\.qq\.com/sph/[A-Za-z0-9_-]{4,256}")
_BAD_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


@dataclass(frozen=True, slots=True)
class YuanbaoReference:
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
    """Decode one reference without asserting the referenced video's identity."""
    if (
        request_method != "POST"
        or _official_url(request_url, _PARSE_HOST, _PARSE_PATH) is None
        or _official_url(response_url, _PARSE_HOST, _PARSE_PATH) is None
        or "?" in str(request_url)
        or "?" in str(response_url)
        or not isinstance(http_status, int)
        or isinstance(http_status, bool)
        or not 200 <= http_status < 300
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
            max_num_fields=2,
        )
    except (UnicodeError, ValueError):
        return None
    if set(query) != {"token", "eid"} or any(
        len(values) != 1 for values in query.values()
    ):
        return None
    token, export_id = query["token"][0], query["eid"][0]
    if not _safe_text(token, 2048) or not _safe_text(export_id, 512):
        return None
    return YuanbaoReference(canonical_share_url, token, export_id)


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
