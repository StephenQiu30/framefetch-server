"""Extractor for one episode from an official Hongguo share page."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from yt_dlp.extractor.common import InfoExtractor  # type: ignore[import-untyped]
from yt_dlp.utils import ExtractorError  # type: ignore[import-untyped]

from ._content_access import reject

_PLAYER_URL = "https://hongguoduanju.com/player/{series_id}/{vid}"
_SHARE_HOSTS = ("novelquickapp.com",)
_MEDIA_HOST_SUFFIX = ".qznovelvod.com"
_ID = r"[0-9]+"
_BROWSER_HEADERS = {
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
}
_SHARE_HEADERS = {
    **_BROWSER_HEADERS,
    "Referer": "https://novelquickapp.com/",
}
_ROUTER_DATA_PATTERN = r"(?:window\.)?_ROUTER_DATA\s*=\s*"


class HongguoOfficialShareIE(InfoExtractor):  # type: ignore[misc]
    """Resolve the current episode from Hongguo's first-party share flow.

    The share page's ``play_url`` is intentionally not used: it is a bounded
    preview URL.  We use the IDs present in the official share state to open
    the first-party player page for the same episode and extract its signed
    MP4 source.
    """

    IE_NAME = "hongguo:official_share"
    _VALID_URL = rf"""(?x)https?://(?:
        (?:www\.)?novelquickapp\.com/s/(?P<share_id>[A-Za-z0-9_-]+)
        |(?:www\.)?novelquickapp\.com/hongguo/ug/pages/video-animation-share
        |(?:www\.)?hongguoduanju\.com/player/(?P<series_id>{_ID})
            (?:/(?P<vid>{_ID}))?
    )(?:[/?#]|$)"""

    def _real_extract(self, url: str) -> dict[str, Any]:
        match = self._match_valid_url(url)
        share_id = match.group("share_id")
        if share_id is not None or _is_h5_share_url(url):
            series_id, vid, title = self._resolve_share(url, share_id or "share")
            player_url = _PLAYER_URL.format(series_id=series_id, vid=vid)
        else:
            series_id = match.group("series_id")
            requested_vid = match.group("vid")
            if series_id is None:
                raise ExtractorError(
                    "Hongguo official player identity is unavailable", expected=True
                )
            player_url = url
            vid = requested_vid
            title = None

        webpage = self._download_webpage(
            player_url,
            vid or series_id,
            note="Downloading Hongguo official player page",
            fatal=False,
            headers=_BROWSER_HEADERS,
        )
        if not webpage:
            raise ExtractorError(
                "Hongguo official player page is unavailable", expected=True
            )

        router_data = self._search_json(
            _ROUTER_DATA_PATTERN,
            webpage,
            "Hongguo player router data",
            vid or series_id,
            fatal=False,
        )
        page = _find_player_page(router_data)
        if page is None:
            raise ExtractorError(
                "Hongguo official player data is unavailable", expected=True
            )
        _enforce_public_clear(page)

        actual_series_id = _identifier(page.get("series_id"))
        actual_vid = _identifier(page.get("vid"))
        if actual_series_id != series_id or (vid is not None and actual_vid != vid):
            raise ExtractorError(
                "Hongguo official player identity mismatch", expected=True
            )

        player_info = _mapping(page.get("video_player_info"))
        media_url = _https_url(player_info.get("main_url") if player_info else None)
        if media_url is None or not _is_official_media_url(media_url):
            raise ExtractorError(
                "Hongguo official player has no authorized MP4 source", expected=True
            )

        series_detail = _mapping(page.get("seriesDetail")) or {}
        vid_list = _string_list(series_detail.get("vid_list"))
        episode_number = (
            vid_list.index(actual_vid) + 1 if actual_vid in vid_list else None
        )
        series_title = str(series_detail.get("series_name") or title or series_id)
        episode_title = (
            f"{series_title} 第{episode_number}集"
            if episode_number is not None
            else (title or series_title)
        )
        duration = _positive_number(
            player_info.get("duration") if player_info else None
        )
        thumbnail = _https_url(
            player_info.get("poster_url") if player_info else None
        ) or _https_url(series_detail.get("series_cover"))
        width = _positive_int(player_info.get("width") if player_info else None)
        height = _positive_int(player_info.get("height") if player_info else None)

        media_format: dict[str, Any] = {
            "format_id": "source-mp4",
            "url": media_url,
            "ext": "mp4",
            "protocol": "https",
            "width": width,
            "height": height,
            "http_headers": {
                **_BROWSER_HEADERS,
                "Referer": player_url,
            },
        }
        return {
            "id": actual_vid,
            "title": episode_title,
            "description": series_detail.get("series_intro"),
            "duration": duration,
            "thumbnail": thumbnail,
            "formats": [media_format],
            "webpage_url": player_url,
            "series": series_title,
            "series_id": series_id,
            "episode_number": episode_number,
            "episode_count": _positive_int(series_detail.get("episode_cnt")),
            "live_status": "not_live",
        }

    def _resolve_share(self, url: str, display_id: str) -> tuple[str, str, str | None]:
        webpage, response = self._download_webpage_handle(
            url,
            display_id,
            note="Downloading Hongguo official share page",
            headers=_SHARE_HEADERS,
        )
        final_url = str(getattr(response, "url", url))
        if not _is_first_party_host(final_url, _SHARE_HOSTS):
            raise ExtractorError(
                "Hongguo share link did not resolve to the first-party share page",
                expected=True,
            )
        router_data = self._search_json(
            _ROUTER_DATA_PATTERN,
            webpage,
            "Hongguo share router data",
            display_id,
            fatal=False,
        )
        page_node = _find_loader_node(router_data, "video-animation-share_page")
        if page_node is None:
            raise ExtractorError(
                "Hongguo official share data is unavailable", expected=True
            )
        link_params = _mapping(page_node.get("linkParams")) or {}
        scheme_params = _mapping(link_params.get("schemeParams")) or {}
        series_id = _identifier(scheme_params.get("video_id"))
        vid = _identifier(scheme_params.get("vid"))
        page_data = _mapping(page_node.get("pageData")) or {}
        chapter_ids = _string_list(page_data.get("chapter_ids"))
        chapter_order = _positive_int(page_data.get("chapter_order"))
        if (
            series_id is None
            or vid is None
            or not chapter_ids
            or chapter_order is None
            or chapter_order > len(chapter_ids)
            or chapter_ids[chapter_order - 1] != vid
        ):
            raise ExtractorError(
                "Hongguo official share episode identity is unavailable",
                expected=True,
            )
        series_data = _mapping(page_data.get("series_data")) or {}
        title = str(series_data.get("title") or "").strip() or None
        return series_id, vid, title


def _find_loader_node(payload: object, suffix: str) -> dict[str, Any] | None:
    root = _mapping(payload)
    loader_data = _mapping(root.get("loaderData")) if root else None
    if loader_data is None:
        return None
    for key, value in loader_data.items():
        if str(key).endswith(suffix) and isinstance(value, dict):
            return value
    return None


def _enforce_public_clear(value: object) -> None:
    """Reject explicit protection/payment metadata before exposing a URL."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key).replace("_", "").casefold()
            if name in {
                "drm",
                "hasdrm",
                "isdrm",
                "isencrypt",
                "isencrypted",
                "encrypted",
                "encryption",
                "decodekey",
                "encryptkey",
            } and item not in (None, False, 0, "", "0", "false", "none"):
                reject("drm_protected")
            if name in {"ispaid", "isvip", "ismemberonly", "requirespurchase"}:
                if item not in (None, False, 0, "", "0", "false"):
                    reject("content_paid_only")
            _enforce_public_clear(item)
    elif isinstance(value, list):
        for item in value:
            _enforce_public_clear(item)


def _find_player_page(payload: object) -> dict[str, Any] | None:
    root = _mapping(payload)
    loader_data = _mapping(root.get("loaderData")) if root else None
    if loader_data is None:
        return None
    for value in loader_data.values():
        if not isinstance(value, dict):
            continue
        if isinstance(value.get("video_player_info"), dict):
            return value
    return None


def _mapping(value: object) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _identifier(value: object) -> str | None:
    candidate = str(value) if value is not None else ""
    return candidate if re.fullmatch(_ID, candidate) else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _positive_number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _positive_int(value: object) -> int | None:
    number = _positive_number(value)
    return int(number) if number is not None else None


def _https_url(value: object) -> str | None:
    candidate = value if isinstance(value, str) else ""
    return candidate if urlsplit(candidate).scheme == "https" else None


def _is_first_party_host(url: str, hosts: tuple[str, ...]) -> bool:
    hostname = (urlsplit(url).hostname or "").casefold()
    return any(hostname == host or hostname.endswith(f".{host}") for host in hosts)


def _is_official_media_url(url: str) -> bool:
    hostname = (urlsplit(url).hostname or "").casefold()
    return hostname.endswith(_MEDIA_HOST_SUFFIX) or hostname == _MEDIA_HOST_SUFFIX[1:]


def _is_h5_share_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        _is_first_party_host(url, _SHARE_HOSTS)
        and parsed.path.rstrip("/") == "/hongguo/ug/pages/video-animation-share"
    )
