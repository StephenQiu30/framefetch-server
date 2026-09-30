from __future__ import annotations

from typing import Any, cast
from urllib.parse import urlsplit

from yt_dlp.extractor.common import InfoExtractor  # type: ignore[import-untyped]
from yt_dlp.extractor.tiktok import DouyinIE  # type: ignore[import-untyped]
from yt_dlp.networking.exceptions import (  # type: ignore[import-untyped]
    HTTPError,
    RequestError,
)
from yt_dlp.utils import ExtractorError, int_or_none  # type: ignore[import-untyped]

from ._content_access import (
    enforce_douyin_access,
)
from ._douyin_visitor import ensure_visitor_cookies
from .douyin_note import DouyinNoteIE

_SHARE_PAGE = "https://www.iesdouyin.com/share/video/{video_id}/"
_DOUYIN_SHORT_URL = r"https?://v\.douyin\.com/(?P<id>[A-Za-z0-9_-]+)/?(?:[?#]|$)"
_ALLOWED_SHARE_HOSTS = frozenset(
    {
        "douyin.com",
        "www.douyin.com",
        "m.douyin.com",
        "v.douyin.com",
        "iesdouyin.com",
        "www.iesdouyin.com",
    }
)
_LINK_UNAVAILABLE = "Douyin official share link unavailable"
_LINK_TEMPORARY = "Douyin official share link temporarily unavailable"
_LINK_SCHEMA_CHANGED = "Douyin official share link response structure changed"
_LINK_VERIFICATION_REQUIRED = "Douyin official share link verification required"
_MOBILE_HEADERS = {
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.douyin.com/",
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
        "Mobile/15E148 Safari/604.1"
    ),
}


class DouyinOfficialShortIE(InfoExtractor):  # type: ignore[misc]
    """Resolve an official Douyin short link to one canonical public video."""

    IE_NAME = "DouyinOfficialShort"
    _VALID_URL = _DOUYIN_SHORT_URL

    def _real_extract(self, url: str) -> dict[str, Any]:
        share_id = self._match_id(url)
        try:
            response = self._request_webpage(
                url,
                share_id,
                note="Resolving Douyin official share link",
                headers=_MOBILE_HEADERS,
            )
        except ExtractorError as exc:
            raise _short_link_error(exc, share_id) from exc

        redirected = getattr(response, "url", None)
        if not isinstance(redirected, str):
            raise ExtractorError(_LINK_SCHEMA_CHANGED, video_id=share_id, expected=True)
        if not _allowed_share_url(redirected):
            raise ExtractorError(_LINK_UNAVAILABLE, video_id=share_id, expected=True)
        if _is_official_note_url(redirected):
            normalized = _canonical_note_url(redirected)
            if normalized is None:
                raise ExtractorError(
                    _LINK_UNAVAILABLE, video_id=share_id, expected=True
                )
            return cast(
                dict[str, Any], self.url_result(normalized, ie=DouyinNoteIE.ie_key())
            )

        normalized = _canonical_video_url(redirected)
        if normalized is None or not _DouyinSharePageIE.suitable(normalized):
            raise ExtractorError(_LINK_UNAVAILABLE, video_id=share_id, expected=True)
        return cast(
            dict[str, Any],
            self.url_result(normalized, ie=_DouyinSharePageIE.ie_key()),
        )


def _correct_download_addr_dimensions(
    info: dict[str, Any], aweme_detail: dict[str, Any]
) -> dict[str, Any]:
    """Align Douyin's download address metadata with the source video dimensions."""

    video = aweme_detail.get("video")
    if not isinstance(video, dict):
        return info
    source_width = int_or_none(video.get("width"))
    source_height = int_or_none(video.get("height"))
    if (
        source_width is None
        or source_height is None
        or source_width <= 0
        or source_height <= 0
        or source_width <= source_height
    ):
        # Upstream already maps Douyin's short-edge resolution correctly for
        # portrait videos. Its width/height assignment is only reversed for
        # landscape download_addr variants.
        return info
    formats = info.get("formats")
    if not isinstance(formats, list):
        return info
    for media_format in formats:
        if not isinstance(media_format, dict):
            continue
        format_id = media_format.get("format_id")
        if isinstance(format_id, str) and format_id.startswith("download_addr"):
            short_edge = int_or_none(media_format.get("width"))
            if short_edge is None or short_edge <= 0:
                continue
            media_format["width"] = round(short_edge * source_width / source_height)
            media_format["height"] = short_edge
    return info


class _DouyinSharePageIE(DouyinIE, plugin_name="share_page"):  # type: ignore[misc, call-arg]
    """Prefer Douyin's public share-page data when the web API needs cookies."""

    def _parse_aweme_video_app(self, aweme_detail: dict[str, Any]) -> dict[str, Any]:
        """Correct download_addr dimensions that Douyin currently under-reports."""

        enforce_douyin_access(aweme_detail)
        return _correct_download_addr_dimensions(
            cast(dict[str, Any], super()._parse_aweme_video_app(aweme_detail)),
            aweme_detail,
        )

    def _real_extract(self, url: str) -> dict[str, Any]:
        video_id = self._match_id(url)
        ensure_visitor_cookies(self, video_id)
        webpage = self._download_webpage(
            _SHARE_PAGE.format(video_id=video_id),
            video_id,
            note="Downloading Douyin public share page",
            fatal=False,
            headers=_MOBILE_HEADERS,
        )
        if webpage:
            router_data = self._search_json(
                r"window\._ROUTER_DATA\s*=\s*",
                webpage,
                "Douyin router data",
                video_id,
                fatal=False,
            )
            item = _router_item(router_data, video_id)
            if item is not None:
                enforce_douyin_access(item)
                try:
                    info = self._parse_aweme_video_app(item)
                except (AttributeError, KeyError, TypeError, ValueError):
                    info = {}
                formats = info.get("formats")
                if isinstance(formats, list) and any(
                    isinstance(media_format, dict)
                    and isinstance(media_format.get("url"), str)
                    and bool(media_format["url"])
                    for media_format in formats
                ):
                    title = " ".join(str(info.get("title") or "").split())
                    info["title"] = title or video_id
                    return info

        return cast(dict[str, Any], super()._real_extract(url))


def _short_link_error(error: ExtractorError, video_id: str) -> ExtractorError:
    cause = error.cause
    if isinstance(cause, HTTPError):
        if cause.status in {404, 410}:
            message = _LINK_UNAVAILABLE
        elif cause.status in {401, 403}:
            message = _LINK_VERIFICATION_REQUIRED
        elif cause.status == 429:
            message = "Douyin official share link rate limited"
        else:
            message = _LINK_TEMPORARY
    elif isinstance(cause, RequestError):
        message = _LINK_TEMPORARY
    else:
        message = _LINK_SCHEMA_CHANGED
    return ExtractorError(message, video_id=video_id, expected=True)


def _allowed_share_url(url: str) -> bool:
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and (parsed.hostname or "").casefold() in _ALLOWED_SHARE_HOSTS
    )


def _is_official_note_url(url: str) -> bool:
    path = urlsplit(url).path.rstrip("/")
    for prefix in ("/note/", "/share/note/"):
        note_id = path.removeprefix(prefix)
        if note_id != path and note_id.isdigit():
            return True
    return False


def _canonical_video_url(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.hostname is None:
        return None
    path = parsed.path.rstrip("/")
    for prefix in ("/video/", "/share/video/"):
        if path.startswith(prefix):
            video_id = path.removeprefix(prefix)
            if video_id.isdigit():
                return f"https://www.douyin.com/video/{video_id}"
    if path == "/jingxuan":
        query = parsed.query.split("&")
        modal_ids = [value[9:] for value in query if value.startswith("modal_id=")]
        if len(modal_ids) == 1 and modal_ids[0].isdigit():
            return f"https://www.douyin.com/video/{modal_ids[0]}"
    return None


def _canonical_note_url(url: str) -> str | None:
    parsed = urlsplit(url)
    path = parsed.path.rstrip("/")
    for prefix in ("/note/", "/share/note/"):
        note_id = path.removeprefix(prefix)
        if note_id != path and note_id.isdigit():
            query = f"?{parsed.query}" if parsed.query else ""
            return f"https://www.iesdouyin.com/share/note/{note_id}/{query}"
    return None


def _router_item(payload: object, expected_id: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    loader_data = payload.get("loaderData")
    if not isinstance(loader_data, dict):
        return None
    for node in loader_data.values():
        if not isinstance(node, dict):
            continue
        response = node.get("videoInfoRes")
        if not isinstance(response, dict):
            continue
        items = response.get("item_list")
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and str(item.get("aweme_id")) == expected_id:
                enforce_douyin_access(item)
                video = item.get("video")
                if not isinstance(video, dict):
                    continue
                normalized = dict(item)
                normalized_video = dict(video)
                if not isinstance(normalized_video.get("bit_rate"), list):
                    normalized_video["bit_rate"] = []
                normalized["video"] = normalized_video
                return normalized
    return None
