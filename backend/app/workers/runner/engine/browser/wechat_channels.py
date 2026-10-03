"""Resolve a bound official share through native Yuanbao and fixed feed requests."""

from __future__ import annotations

import asyncio
import json
import math
import unicodedata
from collections.abc import Mapping
from dataclasses import fields, replace
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from app.services.provider_failures import FailureClass
from app.workers.identity.yuanbao_parse import validate_canonical_share_url
from app.workers.runner.engine.browser.intercept import MAX_RESPONSE_BYTES, failure
from app.workers.runner.engine.identity import NativePageIdentity
from app.workers.runner.engine.layers.base import LayerFailure
from app.workers.runner.engine.resolved import ResolvedMedia
from app.workers.runner.engine.run_context import ResolutionSource, RunContext
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.metadata import enrich_format_metadata
from app.workers.runner.url_policy import UrlPolicyError, validate_media_url
from app.workers.runner.utilities import normalize_for_settings
from app.workers.runner.wechat_channels_native import parse_yuanbao_share
from app.workers.runner.wechat_channels_policy import (
    ProtectionScanLimitError,
    author_info,
    enforce_known_restrictions,
    feed_info,
    has_protection_material,
    strict_official_video_formats,
)
from app.workers.runner.wechat_channels_response import (
    authenticated_feed_info,
    successful_response_data,
    yuanbao_reference,
)

CLIENT = "wechat_channels:browser"
_ORIGIN = "https://channels.weixin.qq.com"
_FEED_URL = f"{_ORIGIN}/finder-preview/api/feed/get_feed_info"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
_HTTP_TIMEOUT = 10.0


async def resolve(source: ResolutionSource, ctx: RunContext) -> ResolvedMedia:
    """Keep account authentication in Chrome; hand off only official clear files."""
    profile = source.request.profile
    if (
        profile.key != "wechat_channels"
        or profile.content_scope != "official_share"
        or profile.identity_source != "yuanbao_native"
        or ctx.cookie_file is not None
        or ctx.browser is not None
        or ctx.identity is not None
        and not isinstance(ctx.identity, NativePageIdentity)
    ):
        raise failure(FailureClass.INVALID_INPUT, "unexpected_identity", "none")
    canonical_url = source.request.source_url
    try:
        validate_canonical_share_url(canonical_url)
    except (TypeError, ValueError):
        raise failure(FailureClass.INVALID_INPUT, "invalid_share_url", "none") from None
    if ctx.deadline.utcoffset() is None:
        raise failure(FailureClass.INVALID_INPUT, "invalid_deadline", "none")
    remaining = (ctx.deadline - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise TimeoutError
    if source.expected_context is not None and source.expected_context.client != CLIENT:
        raise failure(FailureClass.CONTEXT_CHANGED, "client_context_changed", "none")
    async with asyncio.timeout(remaining):
        return await _resolve(source, ctx, canonical_url)


async def _resolve(
    source: ResolutionSource, ctx: RunContext, canonical_url: str
) -> ResolvedMedia:
    short_id = canonical_url.rsplit("/", 1)[-1]
    preview_url = f"{_ORIGIN}/finder-preview/pages/sph?id={short_id}"
    ctx = replace(ctx, user_agent=ctx.user_agent or _USER_AGENT, referer=preview_url)
    await _official_request(ctx, preview_url)
    anonymous_body = {"baseReq": {"generalToken": ""}, "shortUri": short_id}
    anonymous_response, anonymous_payload = await _official_request(
        ctx, _FEED_URL, anonymous_body
    )
    if (
        not _observed_request_matches(anonymous_response, _FEED_URL, anonymous_body)
        or (anonymous := feed_info(anonymous_payload)) is None
    ):
        raise failure(FailureClass.EXTRACTOR_BROKEN, "anonymous_feed_invalid")
    _admit_feed_schema(anonymous_payload, anonymous, require_video=False)
    _admit(anonymous_payload)

    parsed = await parse_yuanbao_share(
        canonical_url, source.workspace.path.name, ctx.deadline
    )
    if not isinstance(parsed.identity, NativePageIdentity):
        raise failure(FailureClass.IDENTITY_UNAVAILABLE, "native_identity_invalid", "③")
    expected_digest = (
        source.expected_context.identity_digest
        if source.expected_context is not None
        else ctx.identity.digest
        if isinstance(ctx.identity, NativePageIdentity)
        else None
    )
    if expected_digest is not None and parsed.identity.digest != expected_digest:
        raise failure(FailureClass.CONTEXT_CHANGED, "identity_account_changed", "none")
    ctx = replace(ctx, identity=parsed.identity, cookie_file=None, browser=None)
    captured = parsed.captured
    reference = yuanbao_reference(
        request_method=captured.get("request_method"),
        request_url=captured.get("request_url"),
        response_url=captured.get("response_url"),
        http_status=captured.get("http_status"),
        request_body=captured.get("request_body"),
        canonical_share_url=canonical_url,
        payload=captured.get("payload"),
    )
    if reference is None:
        raise failure(FailureClass.EXTRACTOR_BROKEN, "native_reference_invalid")
    native_payload = captured.get("payload")
    _admit(native_payload)
    native_metadata = successful_response_data(native_payload, "code")

    official_body = {
        "baseReq": {"generalToken": reference.token},
        "exportId": reference.export_id,
    }
    official_response, official_payload = await _official_request(
        ctx, _FEED_URL, official_body
    )
    official = authenticated_feed_info(
        request_method=official_response.request.method,
        request_url=str(official_response.request.url),
        response_url=str(official_response.url),
        http_status=official_response.status_code,
        request_body=_decode(official_response.request.content),
        reference=reference,
        payload=official_payload,
    )
    if official is None:
        raise failure(FailureClass.EXTRACTOR_BROKEN, "official_feed_invalid")
    _admit_feed_schema(official_payload, official, require_video=True)
    _admit(official_payload)
    title, author, cover = _match_metadata(
        anonymous,
        author_info(anonymous_payload),
        native_metadata,
        official,
        author_info(official_payload),
    )
    try:
        candidates = strict_official_video_formats(official)
    except ValueError:
        raise failure(
            FailureClass.FORMAT_UNAVAILABLE, "official_candidate_missing"
        ) from None
    commands = source.pipeline._commands.with_context(ctx)
    formats: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            probe = await commands.probe_remote(
                candidate["url"], source.workspace.path, referer=ctx.referer
            )
        except RunnerFailure as error:
            if error.code != "media_probe_failed":
                raise
            continue
        enriched = enrich_format_metadata(candidate, probe)
        if _probed_video(enriched):
            formats.append(enriched)
    if not formats:
        raise failure(FailureClass.FORMAT_UNAVAILABLE, "official_media_probe_failed")
    duration = float(formats[0]["duration"])
    if any(
        abs(float(item["duration"]) - duration) > max(1.0, duration * 0.02)
        for item in formats[1:]
    ):
        raise failure(
            FailureClass.CONTEXT_CHANGED, "candidate_duration_mismatch", "none"
        )
    normalized = normalize_for_settings(
        {
            "id": short_id,
            "title": title,
            "uploader": author,
            "thumbnail": cover,
            "webpage_url": canonical_url,
            "extractor_key": "WechatChannelsPublic",
            # This is the probed official candidate's duration, not an original
            # duration or an assertion that this share is public or free.
            "duration": duration,
            "formats": formats,
        },
        source.pipeline._settings,
    )
    return ResolvedMedia(
        **{field.name: getattr(normalized, field.name) for field in fields(normalized)},
        client=CLIENT,
        handoff="http",
        run_context=ctx,
    )


async def _official_request(
    ctx: RunContext, url: str, body: Mapping[str, Any] | None = None
) -> tuple[httpx.Response, object]:
    remaining = (ctx.deadline - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise TimeoutError
    headers = {
        "User-Agent": ctx.user_agent,
        "Referer": ctx.referer,
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if body is not None:
        headers.update(
            {
                "Origin": _ORIGIN,
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
    try:
        # A fresh client for every request prevents preview Set-Cookie from
        # becoming an undeclared identity on either feed request.
        async with httpx.AsyncClient(
            proxy=ctx.egress.proxy_url,
            trust_env=False,
            follow_redirects=False,
            timeout=min(_HTTP_TIMEOUT, remaining),
            headers=headers,
        ) as client:
            async with client.stream(
                "GET" if body is None else "POST", url, json=body
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise failure(
                        FailureClass.RATE_LIMITED
                        if response.status_code == 429
                        else FailureClass.TRANSIENT
                        if response.status_code >= 500
                        else FailureClass.EXTRACTOR_BROKEN,
                        "official_request_rejected",
                    )
                if str(response.request.url) != url or str(response.url) != url:
                    raise failure(
                        FailureClass.EXTRACTOR_BROKEN, "official_request_changed"
                    )
                length = response.headers.get("content-length")
                if length is not None and (
                    len(length) > 20
                    or not length.isascii()
                    or not length.isdigit()
                    or int(length) > MAX_RESPONSE_BYTES
                ):
                    raise failure(
                        FailureClass.EXTRACTOR_BROKEN, "official_response_size_limit"
                    )
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise failure(
                            FailureClass.EXTRACTOR_BROKEN,
                            "official_response_size_limit",
                        )
                    raw.extend(chunk)
                return response, _decode(raw) if body is not None else None
    except LayerFailure:
        raise
    except httpx.TimeoutException:
        raise failure(FailureClass.TRANSIENT, "official_request_timeout") from None
    except httpx.HTTPError:
        raise failure(FailureClass.NETWORK_BLOCKED, "official_request_failed") from None


def _decode(raw: bytes | bytearray) -> object:
    try:
        return json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except (ValueError, TypeError, RecursionError):
        raise failure(
            FailureClass.EXTRACTOR_BROKEN, "official_response_invalid"
        ) from None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise ValueError("non-finite JSON number")


def _observed_request_matches(
    response: httpx.Response, url: str, body: Mapping[str, Any]
) -> bool:
    return (
        response.request.method == "POST"
        and str(response.request.url) == url
        and str(response.url) == url
        and _decode(response.request.content) == body
    )


def _admit(payload: object) -> None:
    try:
        if has_protection_material(payload):
            raise failure(FailureClass.CONTENT_PROTECTED, "protected_media", "none")
        enforce_known_restrictions(payload)
    except ProtectionScanLimitError:
        raise failure(
            FailureClass.EXTRACTOR_BROKEN, "response_structure_limit"
        ) from None
    except RunnerFailure as error:
        if isinstance(error, LayerFailure):
            raise
        raise failure(
            error.failure.failure_class, "restricted_content", "none"
        ) from None


def _admit_feed_schema(
    payload: object, feed: Mapping[str, Any], *, require_video: bool
) -> None:
    data = successful_response_data(payload, "errCode")
    error = data.get("errMsg")
    if not isinstance(error, Mapping) or type(error.get("type")) is not int:
        raise failure(FailureClass.EXTRACTOR_BROKEN, "official_page_state_invalid")
    # Official No_Err is 0. Error/warning/info/redirect pages cannot grant
    # candidate access merely because they also carry errCode=0 and feedInfo.
    if error["type"] != 0:
        raise failure(
            FailureClass.CONTENT_UNAVAILABLE, "official_page_restricted", "none"
        )
    if "mediaType" not in feed and not require_video:
        return
    if type(feed.get("mediaType")) is not int or feed["mediaType"] != 4:
        raise failure(FailureClass.EXTRACTOR_BROKEN, "official_video_type_invalid")


def _match_metadata(
    anonymous: Mapping[str, Any],
    anonymous_author: Mapping[str, Any],
    native: Mapping[str, Any],
    official: Mapping[str, Any],
    official_author: Mapping[str, Any],
) -> tuple[str, str, str]:
    titles = tuple(
        _text(value)
        for value in (
            anonymous.get("description"),
            native.get("desc"),
            official.get("description"),
        )
    )
    authors = tuple(
        _text(value)
        for value in (
            anonymous_author.get("nickname"),
            native.get("author"),
            official_author.get("nickname"),
        )
    )
    covers = tuple(
        _cover(value)
        for value in (
            anonymous.get("coverUrl"),
            native.get("cover_url"),
            official.get("coverUrl"),
        )
    )
    if any(value is None for value in (*titles, *authors, *covers)):
        raise failure(FailureClass.EXTRACTOR_BROKEN, "share_metadata_missing")
    if len(set(titles)) != 1 or len(set(authors)) != 1 or len(set(covers)) != 1:
        raise failure(FailureClass.CONTEXT_CHANGED, "share_metadata_mismatch", "none")
    # The three covers may carry different opaque query tickets for the same
    # HTTPS host and path. Tickets are never decoded or exported in diagnostics.
    return str(titles[0]), str(authors[0]), str(official["coverUrl"])


def _text(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or len(value) > 4096
        or any(
            unicodedata.category(character) in {"Cf", "Cs"}
            or unicodedata.category(character) == "Cc"
            and not character.isspace()
            for character in value
        )
    ):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _cover(value: object) -> tuple[str, str] | None:
    if (
        not isinstance(value, str)
        or "#" in value
        or any(
            character.isspace() or unicodedata.category(character) in {"Cc", "Cf", "Cs"}
            for character in value
        )
    ):
        return None
    try:
        validated = validate_media_url(value)
        parsed = urlsplit(validated.value)
    except UrlPolicyError:
        return None
    if validated.scheme != "https" or not parsed.path or parsed.hostname is None:
        return None
    return parsed.hostname, parsed.path


def _probed_video(value: Mapping[str, Any]) -> bool:
    codec = value.get("vcodec")
    audio_codec = value.get("acodec")
    return (
        isinstance(codec, str)
        and bool(codec)
        and codec.casefold() not in {"none", "unknown"}
        and isinstance(audio_codec, str)
        and bool(audio_codec)
        and audio_codec.casefold() != "unknown"
        and all(
            _positive_finite(value.get(key))
            for key in ("width", "height", "fps", "duration")
        )
    )


def _positive_finite(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and value > 0
    except OverflowError:
        return False
