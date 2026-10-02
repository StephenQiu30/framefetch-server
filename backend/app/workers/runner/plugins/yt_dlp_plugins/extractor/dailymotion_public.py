"""Public Dailymotion access and clear VOD checks around the pinned extractor.

The original API fields are inspected before upstream discards them. Anonymous
playback is accepted only with public publication evidence and a complete stream;
this module neither reads account materials nor handles encrypted media.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from contextlib import closing
from ipaddress import ip_address
from typing import Any, cast
from urllib.parse import urljoin, urlsplit

from yt_dlp.extractor.dailymotion import DailymotionIE  # type: ignore[import-untyped]

from ._content_access import reject

_MAX_MANIFEST_BYTES = 2_000_000
_MAX_FORMATS = 64
_PUBLIC_ID = re.compile(r"x[0-9a-z]+")
_PROTECTION_TAGS = ("#EXT-X-KEY", "#EXT-X-SESSION-KEY")
_UNSUPPORTED_HLS_TAGS = (
    "#EXT-X-MAP",
    "#EXT-X-BYTERANGE",
    "#EXT-X-PART",
    "#EXT-X-PRELOAD-HINT",
    "#EXT-X-I-FRAME",
    "#EXT-X-I-FRAMES-ONLY",
    "#EXT-X-GAP",
    "#EXT-X-SKIP",
)
_ACCESS_FIELDS = "id,private,password_protected,published,status,duration,geoblocking"
_PLAYER_PREFIX = "https://www.dailymotion.com/player/metadata/video/"
_HLS_TYPES = frozenset({"application/x-mpegURL"})
_MEDIA_TYPES = _HLS_TYPES | {"video/mp4"}


def public_media_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 4096 or "\\" in value:
        reject("content_access_metadata_invalid")
    if any(character.isspace() or ord(character) < 32 for character in value):
        reject("content_access_metadata_invalid")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        reject("content_access_metadata_invalid")
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or "." not in host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 80 if parsed.scheme == "http" else 443)
        or host.endswith((".local", ".internal", ".localhost", ".home.arpa"))
    ):
        reject("content_access_metadata_invalid")
    try:
        ip_address(host)
    except ValueError:
        pass
    else:
        reject("content_access_metadata_invalid")
    return value


def positive_duration(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        reject("content_access_metadata_invalid")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        reject("content_access_metadata_invalid")
    return number


def same_duration(actual: object, expected: float) -> None:
    if abs(positive_duration(actual) - expected) > max(3, expected * 0.02):
        reject("content_preview_only")


def public_video_access(payload: object, video_id: str) -> float:
    """Validate documented first-party fields; absence is never a public flag."""
    if not _PUBLIC_ID.fullmatch(video_id) or not isinstance(payload, Mapping):
        reject("content_access_metadata_invalid")
    if payload.get("id") != video_id:
        reject("content_access_metadata_invalid")
    for name in ("private", "password_protected", "published"):
        if not isinstance(payload.get(name), bool):
            reject("content_access_metadata_invalid")
    if payload["private"] or payload["password_protected"]:
        reject("content_private")
    if not payload["published"] or payload.get("status") != "published":
        reject("content_access_metadata_invalid")
    geoblocking = payload.get("geoblocking")
    if not isinstance(geoblocking, list) or any(
        not isinstance(country, str) for country in geoblocking
    ):
        reject("content_access_metadata_invalid")
    if geoblocking not in ([], ["allow"]):
        reject("provider_geo_restricted")
    reject_content_restrictions(payload)
    return positive_duration(payload.get("duration"))


def clear_manifest_lines(document: object) -> list[str]:
    if not isinstance(document, str) or len(document.encode()) > _MAX_MANIFEST_BYTES:
        reject("content_access_metadata_invalid")
    lines = [line.strip() for line in document.splitlines() if line.strip()]
    if not lines or lines[0] != "#EXTM3U":
        reject("content_access_metadata_invalid")
    if any(line.upper().startswith(_PROTECTION_TAGS) for line in lines):
        reject("drm_protected")
    if any(line.upper().startswith(_UNSUPPORTED_HLS_TAGS) for line in lines):
        reject("content_access_metadata_invalid")
    return lines


def clear_vod_manifest(document: str, manifest_url: str, duration: float) -> str:
    """Bind a finite media playlist to original duration, without fetching a key."""
    lines = clear_manifest_lines(document)
    if "#EXT-X-ENDLIST" not in lines or not any(
        line.startswith("#EXT-X-TARGETDURATION:") for line in lines
    ):
        reject("content_access_metadata_invalid")
    if any(
        line.startswith(("#EXT-X-STREAM-INF:", "#EXT-X-MEDIA:", "#EXT-X-PART:"))
        for line in lines
    ):
        reject("content_access_metadata_invalid")
    durations = []
    segments = []
    expecting_segment = False
    for line in lines:
        if line.startswith("#EXTINF:"):
            if expecting_segment:
                reject("content_access_metadata_invalid")
            try:
                seconds = float(line.partition(":")[2].partition(",")[0])
            except ValueError:
                reject("content_access_metadata_invalid")
            durations.append(positive_duration(seconds))
            expecting_segment = True
        elif not line.startswith("#"):
            if not expecting_segment:
                reject("content_access_metadata_invalid")
            segment = urljoin(manifest_url, line)
            segments.append(public_media_url(segment))
            expecting_segment = False
    if expecting_segment or not segments or len(durations) != len(segments):
        reject("content_access_metadata_invalid")
    same_duration(sum(durations), duration)
    return segments[0]


def single_video_result(
    payload: object, video_id: str, duration: float
) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("id") != video_id:
        reject("content_access_metadata_invalid")
    if payload.get("entries") is not None or payload.get("_type", "video") != "video":
        reject("content_access_metadata_invalid")
    if payload.get("is_live") not in (None, False):
        reject("content_access_metadata_invalid")
    if payload.get("live_status") not in (None, "not_live"):
        reject("content_access_metadata_invalid")
    reject_content_restrictions(payload)
    same_duration(payload.get("duration"), duration)
    formats = payload.get("formats")
    if not isinstance(formats, list) or not 0 < len(formats) <= _MAX_FORMATS:
        reject("content_access_metadata_invalid")
    return payload


def reject_content_restrictions(payload: Mapping[str, Any]) -> None:
    """An explicit known restriction must not disappear during normalization."""
    groups = (
        (("has_drm", "is_encrypted"), "drm_protected"),
        (("is_preview", "preview_only"), "content_preview_only"),
        (
            ("requires_purchase", "is_paid", "is_premium", "is_member_only"),
            "content_paid_only",
        ),
    )
    for fields, reason in groups:
        for field in fields:
            if field in payload and payload[field] is not False:
                reject(reason)
    if payload.get("availability") not in (None, "public"):
        reject("content_private")


def public_player_metadata(
    payload: object, video_id: str, duration: float
) -> dict[str, Any]:
    """Fields observed on the anonymous recorded-video player; no defaults."""
    if not isinstance(payload, dict) or payload.get("id") != video_id:
        reject("content_access_metadata_invalid")
    for name in ("private", "is_password_protected", "protected_delivery"):
        if not isinstance(payload.get(name), bool):
            reject("content_access_metadata_invalid")
        if payload[name]:
            reject(
                "content_private" if name != "protected_delivery" else "drm_protected"
            )
    if (
        payload.get("mode") != "vod"
        or payload.get("stream_type") != "recorded"
        or payload.get("media_type") != "video"
    ):
        reject("content_access_metadata_invalid")
    stream_formats = payload.get("stream_formats")
    if (
        not isinstance(stream_formats, dict)
        or not stream_formats
        or any(
            not isinstance(quality, str) or stream_format != "mpegts"
            for quality, stream_format in stream_formats.items()
        )
    ):
        reject("content_access_metadata_invalid")
    reject_content_restrictions(payload)
    same_duration(payload.get("duration"), duration)
    return payload


class _DailymotionPublicIE(DailymotionIE, plugin_name="public_access"):  # type: ignore[misc, call-arg]
    """Retain the upstream anonymous token/parser; add original access evidence."""

    _video_id = ""
    _full_duration: float | None = None
    _player_checked = False
    _reading_manifest = False
    _manifest_request: dict[str, Any]
    _manifest_response_urls: dict[str, str]

    def _real_extract(self, url: str) -> dict[str, Any]:
        matched = self._match_valid_url(url)
        video_id = matched.group("id")
        if matched.group("is_playlist") or not _PUBLIC_ID.fullmatch(video_id):
            reject("content_access_metadata_invalid")
        self._video_id = video_id
        self._full_duration = None
        self._player_checked = False
        self._manifest_request = {}
        self._manifest_response_urls = {}
        access = self._download_json(
            f"https://api.dailymotion.com/video/{video_id}",
            video_id,
            note="Downloading Dailymotion public access metadata",
            query={"fields": _ACCESS_FIELDS},
        )
        self._full_duration = public_video_access(access, video_id)
        result = single_video_result(
            super()._real_extract(url), video_id, self._full_duration
        )
        if not self._player_checked:
            reject("content_access_metadata_invalid")
        for item in result["formats"]:
            if not isinstance(item, dict) or item.get("has_drm") is True:
                reject("drm_protected")
            public_media_url(item.get("url"))
            if str(item.get("protocol") or "").startswith("m3u8"):
                if not isinstance(item.get("hls_media_playlist_data"), str):
                    reject("content_access_metadata_invalid")
            elif str(item.get("protocol") or "https") not in {"http", "https"}:
                reject("content_access_metadata_invalid")
        result["duration"] = self._full_duration
        result["availability"] = "public"
        result["_framefetch_full_stream"] = True
        return result

    def _call_api(self, *args: Any, **kwargs: Any) -> Any:
        result = super()._call_api(*args, **kwargs)
        if not isinstance(result, dict) or result.get("xid") != self._video_id:
            reject("content_access_metadata_invalid")
        if result.get("isOnAir") not in (None, False):
            reject("content_access_metadata_invalid")
        return result

    def _download_json(
        self, url_or_request: Any, video_id: str, *args: Any, **kwargs: Any
    ) -> Any:
        player_request = isinstance(url_or_request, str) and url_or_request.startswith(
            _PLAYER_PREFIX
        )
        if player_request and url_or_request != _PLAYER_PREFIX + self._video_id:
            reject("content_access_metadata_invalid")
        result = super()._download_json(url_or_request, video_id, *args, **kwargs)
        if player_request:
            if not isinstance(result, dict):
                reject("content_access_metadata_invalid")
            if result.get("error"):
                return result  # Preserve upstream's fixed platform error handling.
            result = public_player_metadata(
                result, self._video_id, positive_duration(self._full_duration)
            )
            qualities = result.get("qualities")
            if not isinstance(qualities, dict) or not qualities:
                reject("content_access_metadata_invalid")
            checked: dict[str, list[dict[str, Any]]] = {}
            for quality, media in qualities.items():
                if not isinstance(quality, str) or not isinstance(media, list):
                    reject("content_access_metadata_invalid")
                for item in media:
                    if not isinstance(item, dict):
                        reject("content_access_metadata_invalid")
                    reject_content_restrictions(item)
                    if item.get("type") in _MEDIA_TYPES:
                        public_media_url(item.get("url"))
                        checked.setdefault(quality, []).append(item)
            if not checked:
                reject("content_access_metadata_invalid")
            result = {**result, "qualities": checked}
            self._player_checked = True
        return result

    def _extract_dailymotion_m3u8_formats_and_subtitles(
        self, media_url: str, video_id: str, live: bool = False
    ) -> Any:
        if live or not self._player_checked or self._full_duration is None:
            reject("content_access_metadata_invalid")
        public_media_url(media_url)
        self._reading_manifest = True
        try:
            # Keep the pinned extractor's TLS/header retry behavior.
            return super()._extract_dailymotion_m3u8_formats_and_subtitles(
                media_url, video_id, live=False
            )
        finally:
            self._reading_manifest = False

    def _download_webpage_handle(
        self, url_or_request: Any, video_id: str, *args: Any, **kwargs: Any
    ) -> Any:
        if not self._reading_manifest:
            return super()._download_webpage_handle(
                url_or_request, video_id, *args, **kwargs
            )
        self._manifest_request = {
            key: kwargs[key]
            for key in ("headers", "impersonate", "require_impersonation")
            if key in kwargs
        }
        request_kwargs = {
            key: value for key, value in kwargs.items() if key != "encoding"
        }
        response = self._request_webpage(
            url_or_request, video_id, *args, **request_kwargs
        )
        if response is False:
            return False
        with closing(response):
            final_url = public_media_url(response.url)
            self._manifest_response_urls[public_media_url(url_or_request)] = final_url
            body = response.read(_MAX_MANIFEST_BYTES + 1)
            if len(body) > _MAX_MANIFEST_BYTES:
                reject("content_access_metadata_invalid")
            try:
                document = body.decode("utf-8")
            except UnicodeDecodeError:
                reject("content_access_metadata_invalid")
        return document, response

    def _parse_m3u8_formats_and_subtitles(
        self, m3u8_doc: str, m3u8_url: str, *args: Any, **kwargs: Any
    ) -> Any:
        m3u8_url = self._manifest_response_urls.get(m3u8_url, m3u8_url)
        public_media_url(m3u8_url)
        clear_manifest_lines(m3u8_doc)  # Before the upstream parser sees any key.
        if self._full_duration is None or kwargs.get("live"):
            reject("content_access_metadata_invalid")
        formats, subtitles = super()._parse_m3u8_formats_and_subtitles(
            m3u8_doc, m3u8_url, *args, **kwargs
        )
        if not formats or len(formats) > _MAX_FORMATS:
            reject("content_access_metadata_invalid")
        documents = {m3u8_url: (m3u8_doc, m3u8_url)}
        for item in formats:
            variant_url = public_media_url(item.get("url"))
            if item.get("has_drm") is True:
                reject("drm_protected")
            if variant_url not in documents:
                document = self._download_webpage(
                    variant_url,
                    self._video_id,
                    note="Checking Dailymotion clear VOD rendition",
                    **self._manifest_request,
                )
                if not isinstance(document, str):
                    reject("content_access_metadata_invalid")
                final_url = self._manifest_response_urls.get(variant_url, variant_url)
                documents[variant_url] = document, final_url
            document, final_url = documents[variant_url]
            first_segment = clear_vod_manifest(document, final_url, self._full_duration)
            item["url"] = final_url
            item["hls_media_playlist_data"] = document
            item["_framefetch_probe_url"] = first_segment
        return cast(list[dict[str, Any]], formats), subtitles
