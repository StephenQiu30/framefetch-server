"""Pure URL policies used by declarative provider profiles."""

from __future__ import annotations

import re
from urllib.parse import SplitResult, parse_qs

from app.workers.runner.errors import RunnerFailure
from app.workers.runner.url_policy import UrlPolicyError, validate_media_url

_VIMEO_ID = re.compile(r"/([0-9]+)/?$")
_DAILYMOTION_VIDEO = re.compile(r"/video/(?P<id>[A-Za-z0-9]+)/?$")
_DAILYMOTION_SHORT = re.compile(r"/(?P<id>[A-Za-z0-9]+)/?$")
_DOUYIN_VIDEO = re.compile(r"/video/(?P<id>[0-9]+)/?$")
_DOUYIN_SHARE = re.compile(r"/share/video/(?P<id>[0-9]+)/?$")
_TIKTOK_VIDEO = re.compile(r"/@(?P<user>[A-Za-z0-9_.-]+)/video/(?P<id>[0-9]+)/?$")
_TIKTOK_EMBED = re.compile(r"/embed/(?P<id>[0-9]+)/?$")
_TIKTOK_SHORT = re.compile(r"/(?P<token>[A-Za-z0-9_]+)/?$")
_TIKTOK_WEB_SHORT = re.compile(r"/t/(?P<token>[A-Za-z0-9_]+)/?$")
_KUAISHOU_VIDEO = re.compile(r"/short-video/(?P<id>[A-Za-z0-9]+)/?$")
_SNAPCHAT_SPOTLIGHT = re.compile(r"/spotlight/(?P<id>[A-Za-z0-9_-]+)/?$")
_LINKEDIN_POST = re.compile(
    r"/(?:posts/[^/]+-(?:activity|ugcpost)-[0-9]+-[^/]+"
    r"|feed/update/urn:li:(?:activity|ugcpost):[0-9]+)/?$",
    re.IGNORECASE,
)
_TELEGRAM_POST = re.compile(r"/(?:s/)?[A-Za-z0-9_]+/[0-9]+/?$")
_KICK_CHANNEL = re.compile(r"/(?P<channel>[A-Za-z0-9_-]+)/?$")
_KICK_CLIP = re.compile(
    r"/(?P<channel>[A-Za-z0-9_-]+)/clips/(?P<id>clip_[A-Za-z0-9]+)/?$",
    re.IGNORECASE,
)
_TUMBLR_CURRENT_POST = re.compile(
    r"/(?P<blog>[A-Za-z0-9_-]+)/(?P<id>[0-9]+)(?:/[^/?#]+)?/?$"
)
_TUMBLR_LEGACY_POST = re.compile(r"/post/(?P<id>[0-9]+)(?:/[^/?#]+)?/?$")
_HONGGUO_SHARE = re.compile(r"/s/[A-Za-z0-9_-]+/?$")
_HONGGUO_H5_SHARE = re.compile(r"/hongguo/ug/pages/video-animation-share/?$")
_HONGGUO_PLAYER = re.compile(r"/player/[0-9]+/[0-9]+/?$")
_WECHAT_CHANNELS_SHARE = re.compile(r"/sph/(?P<id>[A-Za-z0-9_-]{4,256})/?$")
_DIGITS = re.compile(r"[0-9]+$")


def vimeo_url(url: str, parsed: SplitResult) -> str:
    match = _VIMEO_ID.fullmatch(parsed.path)
    return url if match is None else f"https://player.vimeo.com/video/{match.group(1)}"


def dailymotion_url(url: str, parsed: SplitResult) -> str:
    """Bind long/short shares to one video, without playlist or tracking context."""
    try:
        validate_media_url(url)
    except UrlPolicyError:
        raise RunnerFailure("provider_unsupported", status=422) from None
    hostname = (parsed.hostname or "").casefold()
    match = (
        _DAILYMOTION_VIDEO.fullmatch(parsed.path)
        if hostname in {"dailymotion.com", "www.dailymotion.com"}
        else _DAILYMOTION_SHORT.fullmatch(parsed.path)
        if hostname == "dai.ly"
        else None
    )
    if match is None:
        raise RunnerFailure("provider_unsupported", status=422)
    return f"https://www.dailymotion.com/video/{match.group('id')}"


def douyin_url(url: str, parsed: SplitResult) -> str:
    match = _DOUYIN_VIDEO.fullmatch(parsed.path) or _DOUYIN_SHARE.fullmatch(parsed.path)
    if match is not None:
        return f"https://www.douyin.com/video/{match.group('id')}"
    modal_id = parse_qs(parsed.query).get("modal_id", [])
    if len(modal_id) == 1 and _DIGITS.fullmatch(modal_id[0]):
        return f"https://www.douyin.com/video/{modal_id[0]}"
    return url


def tiktok_url(_url: str, parsed: SplitResult) -> str:
    hostname = (parsed.hostname or "").casefold()
    video = _TIKTOK_VIDEO.fullmatch(parsed.path)
    if video is not None and hostname in {
        "tiktok.com",
        "www.tiktok.com",
        "m.tiktok.com",
    }:
        return (
            f"https://www.tiktok.com/@{video.group('user')}/video/{video.group('id')}"
        )
    embed = _TIKTOK_EMBED.fullmatch(parsed.path)
    if embed is not None and hostname in {"tiktok.com", "www.tiktok.com"}:
        return f"https://www.tiktok.com/embed/{embed.group('id')}"
    short = _TIKTOK_SHORT.fullmatch(parsed.path)
    if short is not None and hostname in {"vm.tiktok.com", "vt.tiktok.com"}:
        return f"https://{hostname}/{short.group('token')}"
    web_short = _TIKTOK_WEB_SHORT.fullmatch(parsed.path)
    if web_short is not None and hostname in {"tiktok.com", "www.tiktok.com"}:
        return f"https://www.tiktok.com/t/{web_short.group('token')}"
    raise RunnerFailure("provider_unsupported", status=422)


def kuaishou_url(url: str, parsed: SplitResult) -> str:
    match = _KUAISHOU_VIDEO.fullmatch(parsed.path)
    return (
        url
        if match is None
        else f"https://v.m.chenzhongtech.com/fw/photo/{match.group('id')}"
    )


def snapchat_url(url: str, parsed: SplitResult) -> str:
    return _require_path(url, parsed, _SNAPCHAT_SPOTLIGHT)


def linkedin_url(_url: str, parsed: SplitResult) -> str:
    if _LINKEDIN_POST.fullmatch(parsed.path) is None:
        raise RunnerFailure("provider_unsupported", status=422)
    query = parse_qs(parsed.query)
    if not set(query) <= {"utm_source", "utm_medium", "utm_campaign"}:
        raise RunnerFailure("provider_unsupported", status=422)
    return f"https://www.linkedin.com{parsed.path}"


def telegram_url(url: str, parsed: SplitResult) -> str:
    return _require_path(
        url,
        parsed,
        _TELEGRAM_POST,
        allowed_queries=frozenset({"", "single"}),
    )


def kick_url(url: str, parsed: SplitResult) -> str:
    clip_match = _KICK_CLIP.fullmatch(parsed.path)
    if clip_match is not None and not parsed.query:
        return url
    channel_match = _KICK_CHANNEL.fullmatch(parsed.path)
    query = parse_qs(parsed.query)
    clip_ids = query.get("clip", [])
    if (
        channel_match is None
        or set(query) != {"clip"}
        or len(clip_ids) != 1
        or re.fullmatch(r"clip_[A-Za-z0-9]+", clip_ids[0], re.IGNORECASE) is None
    ):
        raise RunnerFailure("provider_unsupported", status=422)
    return f"https://kick.com/{channel_match.group('channel')}/clips/{clip_ids[0]}"


def tumblr_url(url: str, parsed: SplitResult) -> str:
    hostname = (parsed.hostname or "").casefold()
    if parsed.query or parsed.fragment:
        raise RunnerFailure("provider_unsupported", status=422)
    if hostname == "www.tumblr.com":
        return _require_path(url, parsed, _TUMBLR_CURRENT_POST)
    if hostname.endswith(".tumblr.com"):
        match = _TUMBLR_LEGACY_POST.fullmatch(parsed.path)
        blog = hostname.removesuffix(".tumblr.com")
        if match is not None and re.fullmatch(r"[A-Za-z0-9_-]+", blog):
            slug = parsed.path.rstrip("/").split("/")[3:]
            suffix = f"/{slug[0]}" if slug else ""
            return f"https://www.tumblr.com/{blog}/{match.group('id')}{suffix}"
    raise RunnerFailure("provider_unsupported", status=422)


def hongguo_url(url: str, parsed: SplitResult) -> str:
    hostname = (parsed.hostname or "").casefold()
    if parsed.fragment:
        raise RunnerFailure("provider_unsupported", status=422)
    if hostname.endswith("novelquickapp.com"):
        if _HONGGUO_SHARE.fullmatch(parsed.path) is not None and not parsed.query:
            return url
        if _HONGGUO_H5_SHARE.fullmatch(parsed.path) is not None:
            query = parse_qs(parsed.query)
            if query and set(query) <= {"video_id", "vid", "gd_label"}:
                return url
        raise RunnerFailure("provider_unsupported", status=422)
    if hostname.endswith("hongguoduanju.com"):
        if _HONGGUO_PLAYER.fullmatch(parsed.path) is not None and not parsed.query:
            return url
        if parsed.path.rstrip("/") == "/detail":
            series_ids = parse_qs(parsed.query).get("series_id", [])
            if len(series_ids) == 1 and _DIGITS.fullmatch(series_ids[0]):
                raise RunnerFailure("provider_media_unsupported", status=422)
    raise RunnerFailure("provider_unsupported", status=422)


def wechat_channels_url(_url: str, parsed: SplitResult) -> str:
    if (
        parsed.hostname != "weixin.qq.com"
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise RunnerFailure("provider_unsupported", status=422)
    match = _WECHAT_CHANNELS_SHARE.fullmatch(parsed.path)
    if match is None:
        raise RunnerFailure("provider_unsupported", status=422)
    return f"https://weixin.qq.com/sph/{match.group('id')}"


def _require_path(
    url: str,
    parsed: SplitResult,
    pattern: re.Pattern[str],
    *,
    allowed_queries: frozenset[str] = frozenset({""}),
) -> str:
    if pattern.fullmatch(parsed.path) is None or parsed.query not in allowed_queries:
        raise RunnerFailure("provider_unsupported", status=422)
    return url


def qqvideo_url(url: str, parsed: SplitResult) -> str:
    if parsed.port not in (None, 443) or not re.fullmatch(
        r"/x/(?:page|cover/[A-Za-z0-9_]+)/[A-Za-z0-9_]+\.html", parsed.path
    ):
        raise RunnerFailure("provider_unsupported", status=422)
    return f"https://v.qq.com{parsed.path}"


def weibo_url(_url: str, parsed: SplitResult) -> str:
    """Keep share links within the single-post/video extractor boundary."""
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 80 if parsed.scheme == "http" else 443)
    ):
        raise RunnerFailure("provider_unsupported", status=422)
    if host == "t.cn" and re.fullmatch(r"/[A-Za-z0-9]+/?", parsed.path):
        return f"https://t.cn{parsed.path.rstrip('/')}"
    if host in {"weibo.com", "www.weibo.com", "weibo.cn"}:
        if re.fullmatch(r"/[0-9]+/[A-Za-z0-9]+/?", parsed.path):
            return f"https://weibo.com{parsed.path.rstrip('/')}"
        match = re.fullmatch(
            r"/tv/show/([0-9]+:(?:[0-9a-f]{32}|[0-9]{16,}))/?", parsed.path
        )
        if host != "weibo.cn" and match is not None:
            return f"https://weibo.com/tv/show/{match.group(1)}"
    if host == "m.weibo.cn" and re.fullmatch(
        r"/(?:status|detail)/[A-Za-z0-9]+/?", parsed.path
    ):
        return f"https://m.weibo.cn{parsed.path.rstrip('/')}"
    if host == "video.weibo.com" and parsed.path.rstrip("/") == "/show":
        identifiers = parse_qs(parsed.query).get("fid", [])
        if len(identifiers) == 1 and re.fullmatch(
            r"[0-9]+:(?:[0-9a-f]{32}|[0-9]{16,})", identifiers[0]
        ):
            return f"https://weibo.com/tv/show/{identifiers[0]}"
    raise RunnerFailure("provider_unsupported", status=422)
