from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from app.workers.runner.provider_session_headers import (
    SESSION_HEADER_COOKIE,
    SESSION_HEADER_URL,
    decode_session_headers,
)
from app.workers.runner.wechat_channels_policy import (
    author_info,
    feed_info,
    has_protection_material,
    playable_parameters,
    successful_data,
    video_formats,
)
from yt_dlp.extractor.common import InfoExtractor  # type: ignore[import-untyped]
from yt_dlp.utils import ExtractorError  # type: ignore[import-untyped]

_PREVIEW_PAGE = "https://channels.weixin.qq.com/finder-preview/pages/sph?id={video_id}"
_FEED_API = "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"
_YUANBAO_API = "https://yuanbao.tencent.com/api/weixin/get_parse_result"
_YUANBAO_HOME = "https://yuanbao.tencent.com/"
_UNAVAILABLE = "WeChat Channels public link unavailable"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


class WechatChannelsPublicIE(InfoExtractor):  # type: ignore[misc]
    """Resolve one public WeChat Channels share without decrypting media."""

    IE_NAME = "wechat_channels:public"
    _VALID_URL = r"https://weixin\.qq\.com/sph/(?P<id>[A-Za-z0-9_-]{4,256})/?$"

    def _real_extract(self, url: str) -> dict[str, Any]:
        video_id = self._match_id(url)
        canonical_url = f"https://weixin.qq.com/sph/{video_id}"
        preview_url = _PREVIEW_PAGE.format(video_id=video_id)
        self._download_webpage(
            preview_url,
            video_id,
            note="Checking public WeChat Channels share",
            headers=_preview_headers(preview_url),
        )
        public_payload = self._download_json(
            _FEED_API,
            video_id,
            note="Downloading public WeChat Channels metadata",
            data=_json_bytes({"baseReq": {"generalToken": ""}, "shortUri": video_id}),
            headers=_api_headers(preview_url),
        )
        public_feed = feed_info(public_payload)
        if public_feed is None:
            raise ExtractorError(_UNAVAILABLE, expected=True)
        _reject_protected(public_payload)
        public_author = author_info(public_payload)

        feed = public_feed
        author = public_author
        formats = _with_media_headers(video_formats(feed), preview_url)
        parse_data: Mapping[str, Any] = {}
        if not formats:
            cookies = self._get_cookies(_YUANBAO_HOME)
            if not {"hy_user", "hy_token"} <= set(cookies):
                raise ExtractorError(
                    "FrameFetch credential_required: this public WeChat Channels "
                    "video needs the declared Yuanbao session",
                    expected=True,
                )
            account_id = str(cookies["hy_user"].value)
            auth_token = str(cookies["hy_token"].value)
            session_headers = self._get_cookies(SESSION_HEADER_URL)
            encoded_headers = session_headers.get(SESSION_HEADER_COOKIE)
            browser_headers = decode_session_headers(
                str(encoded_headers.value) if encoded_headers is not None else ""
            )
            parse_payload = self._download_json(
                _YUANBAO_API,
                video_id,
                note="Resolving public WeChat Channels share",
                data=_json_bytes(
                    {"type": "video_channel_url", "url": canonical_url, "scene": 1}
                ),
                headers=_yuanbao_headers(account_id, auth_token, browser_headers),
            )
            _reject_protected(parse_payload)
            parse_data = successful_data(parse_payload)
            playable_url = playable_parameters(parse_data)
            if playable_url is None:
                raise ExtractorError(
                    "WeChat Channels resolver returned an unsupported URL",
                    expected=True,
                )
            token, export_id = playable_url
            feed_payload = self._download_json(
                _FEED_API,
                video_id,
                note="Downloading resolved WeChat Channels media metadata",
                data=_json_bytes(
                    {"baseReq": {"generalToken": token}, "exportId": export_id}
                ),
                headers=_api_headers(preview_url),
            )
            _reject_protected(feed_payload)
            feed = feed_info(feed_payload) or {}
            author = author_info(feed_payload) or public_author
            formats = _with_media_headers(video_formats(feed), preview_url)
            if not formats:
                raise ExtractorError(_UNAVAILABLE, expected=True)

        description = _text(feed.get("description")) or _text(
            public_feed.get("description")
        )
        uploader = (
            _text(author.get("nickname")) if isinstance(author, Mapping) else None
        )
        return {
            "id": video_id,
            "title": description or _text(parse_data.get("desc")) or video_id,
            "description": description,
            "uploader": (
                uploader
                or _text(parse_data.get("author"))
                or _text(parse_data.get("nickname"))
            ),
            "thumbnail": _thumbnail(feed) or _thumbnail(public_feed),
            "formats": formats,
            "webpage_url": canonical_url,
        }


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _preview_headers(referer: str) -> dict[str, str]:
    return {
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": referer,
        "User-Agent": _USER_AGENT,
    }


def _api_headers(referer: str) -> dict[str, str]:
    return _preview_headers(referer) | {
        "Content-Type": "application/json",
        "Origin": "https://channels.weixin.qq.com",
        "X-Requested-With": "XMLHttpRequest",
    }


def _yuanbao_headers(
    account_id: str,
    auth_token: str,
    browser_headers: Mapping[str, str],
) -> dict[str, str]:
    return (
        {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Content-Type": "application/json",
            "Origin": "https://yuanbao.tencent.com",
            "Referer": "https://yuanbao.tencent.com/",
            "User-Agent": _USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
        }
        | dict(browser_headers)
        | {
            "T-Userid": account_id,
            "X-Token": auth_token,
            "X-Id": account_id,
        }
    )


def _with_media_headers(
    formats: list[dict[str, Any]], referer: str
) -> list[dict[str, Any]]:
    for item in formats:
        item["http_headers"] = _preview_headers(referer)
    return formats


def _reject_protected(value: object) -> None:
    if has_protection_material(value):
        raise ExtractorError("This video is DRM protected", expected=True)


def _thumbnail(feed: Mapping[str, Any]) -> str | None:
    value = feed.get("coverUrl") or feed.get("cover")
    return value if isinstance(value, str) and value.startswith("https://") else None


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None
