"""Stable, public download-source taxonomy for administrator reporting."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.provider_types import ProviderKey


@dataclass(frozen=True, slots=True)
class DownloadSource:
    key: str
    name: str
    extractor_prefixes: tuple[str, ...]


DOWNLOAD_SOURCES: tuple[DownloadSource, ...] = (
    DownloadSource(ProviderKey.YOUTUBE, "YouTube", ("youtube",)),
    DownloadSource(ProviderKey.BILIBILI, "哔哩哔哩", ("bilibili", "biliintl")),
    DownloadSource(ProviderKey.DOUYIN, "抖音", ("douyin",)),
    DownloadSource(ProviderKey.TIKTOK, "TikTok", ("tiktok",)),
    DownloadSource(ProviderKey.XIAOHONGSHU, "小红书", ("xiaohongshu",)),
    DownloadSource(ProviderKey.KUAISHOU, "快手", ("kuaishou",)),
    DownloadSource(ProviderKey.VIMEO, "Vimeo", ("vimeo",)),
    DownloadSource(ProviderKey.DAILYMOTION, "Dailymotion", ("dailymotion",)),
    DownloadSource(ProviderKey.X, "X / Twitter", ("twitter",)),
    DownloadSource(ProviderKey.INSTAGRAM, "Instagram", ("instagram",)),
    DownloadSource(ProviderKey.FACEBOOK, "Facebook", ("facebook",)),
    DownloadSource(ProviderKey.TWITCH, "Twitch", ("twitch",)),
    DownloadSource(ProviderKey.REDDIT, "Reddit", ("reddit",)),
    DownloadSource(ProviderKey.PINTEREST, "Pinterest", ("pinterest",)),
    DownloadSource(ProviderKey.WEIBO, "微博", ("weibo",)),
    DownloadSource(ProviderKey.YOUKU, "优酷", ("youku",)),
    DownloadSource(
        ProviderKey.QQVIDEO,
        "腾讯视频",
        ("vqqvideo", "qqvideo", "tencentvideo"),
    ),
    DownloadSource("mediatrack", "MediaTrack", ("mediatrack",)),
)
OTHER_DOWNLOAD_SOURCE = DownloadSource("other", "其他来源", ())
BROWSER_IMPORT_DOWNLOAD_SOURCE = DownloadSource("browser_import", "本地视频上传", ())

_SOURCES_BY_KEY = {
    source.key: source for source in (*DOWNLOAD_SOURCES, BROWSER_IMPORT_DOWNLOAD_SOURCE)
}


def download_source(key: str) -> DownloadSource:
    return _SOURCES_BY_KEY.get(key, OTHER_DOWNLOAD_SOURCE)
