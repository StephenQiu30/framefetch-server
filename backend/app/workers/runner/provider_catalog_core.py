"""Core and browser-challenged provider profiles."""

from __future__ import annotations

from app.services.provider_types import (
    ProviderCapability,
    ProviderCookieDomain,
    ProviderIdentity,
    ProviderKey,
    ProviderProfileVersion,
    ProviderSupportStatus,
)
from app.workers.runner.provider_factories import (
    ANDROID_IMPERSONATION,
    challenged_provider,
    standard_provider,
)
from app.workers.runner.provider_normalizers import douyin_url, kuaishou_url, tiktok_url
from app.workers.runner.provider_registry import (
    ProviderProfile,
    ProviderRuntimeSettings,
)


def _youtube_runtime_args(settings: ProviderRuntimeSettings) -> tuple[str, ...]:
    client_args = (
        "--extractor-args",
        "youtube:player_client=mweb",
    )
    if settings.runner_youtube_pot_base_url is None:
        return client_args
    return (
        *client_args,
        "--extractor-args",
        f"youtubepot-bgutilhttp:base_url={settings.runner_youtube_pot_base_url}",
    )


CORE_PROVIDER_PROFILES: tuple[ProviderProfile, ...] = (
    ProviderProfile(
        key=ProviderKey.YOUTUBE,
        display_name="YouTube",
        hosts=frozenset(
            {
                "youtube.com",
                "www.youtube.com",
                "m.youtube.com",
                "music.youtube.com",
                "youtu.be",
                "youtube-nocookie.com",
                "www.youtube-nocookie.com",
            }
        ),
        version=ProviderProfileVersion.YOUTUBE,
        capabilities=frozenset(
            {
                ProviderCapability.SINGLE_VIDEO,
                ProviderCapability.SHORT_VIDEO,
                ProviderCapability.AUDIO_VIDEO_SPLIT,
                ProviderCapability.SUBTITLES,
            }
        ),
        cookie_domain_allowlist=frozenset(
            {
                ProviderCookieDomain.YOUTUBE,
                ProviderCookieDomain.YOUTUBE_NOCOOKIE,
            }
        ),
        client_profile="youtube:mweb",
        support_status=ProviderSupportStatus.UNKNOWN,
        runtime_command_args=_youtube_runtime_args,
        yt_dlp_retry_count=0,
        identity=ProviderIdentity.PREFER,
    ),
    standard_provider(
        ProviderKey.BILIBILI,
        "哔哩哔哩",
        ("bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv"),
        status=ProviderSupportStatus.UNKNOWN,
        identity=ProviderIdentity.PREFER,
        cookie_domain_allowlist=frozenset({"bilibili.com"}),
    ),
    challenged_provider(
        ProviderKey.DOUYIN,
        "抖音",
        (
            "douyin.com",
            "www.douyin.com",
            "m.douyin.com",
            "v.douyin.com",
            "iesdouyin.com",
            "www.iesdouyin.com",
        ),
        version=ProviderProfileVersion.DOUYIN,
        normalize_url=douyin_url,
        status=ProviderSupportStatus.UNKNOWN,
        cookie_domain_allowlist=frozenset(
            {ProviderCookieDomain.DOUYIN, ProviderCookieDomain.DOUYIN_MEDIA}
        ),
        probe_authenticated_media=True,
        probe_media_duration=True,
        identity=ProviderIdentity.PREFER,
    ),
    standard_provider(
        ProviderKey.TIKTOK,
        "TikTok",
        (
            "tiktok.com",
            "www.tiktok.com",
            "m.tiktok.com",
            "vm.tiktok.com",
            "vt.tiktok.com",
        ),
        version=ProviderProfileVersion.TIKTOK,
        normalize_url=tiktok_url,
        capabilities=frozenset(
            {
                ProviderCapability.SINGLE_VIDEO,
                ProviderCapability.SHORT_VIDEO,
                ProviderCapability.AUDIO_VIDEO_SPLIT,
            }
        ),
        status=ProviderSupportStatus.UNKNOWN,
        client_profile="yt-dlp-default",
    ),
    challenged_provider(
        ProviderKey.XIAOHONGSHU,
        "小红书",
        (
            "xiaohongshu.com",
            "www.xiaohongshu.com",
            "xhslink.com",
            "www.xhslink.com",
        ),
        status=ProviderSupportStatus.UNKNOWN,
        cookie_domain_allowlist=frozenset({ProviderCookieDomain.XIAOHONGSHU}),
        identity=ProviderIdentity.PREFER,
    ),
    ProviderProfile(
        key=ProviderKey.KUAISHOU,
        display_name="快手",
        hosts=frozenset(
            {
                "kuaishou.com",
                "www.kuaishou.com",
                "m.kuaishou.com",
                "v.kuaishou.com",
                "kuaishou.cn",
                "www.kuaishou.cn",
                "c.kuaishou.com",
                "v.m.chenzhongtech.com",
                "m.gifshow.com",
            }
        ),
        version=ProviderProfileVersion.KUAISHOU,
        capabilities=frozenset(
            {ProviderCapability.SINGLE_VIDEO, ProviderCapability.SHORT_VIDEO}
        ),
        client_profile="chrome-131-android-14",
        support_status=ProviderSupportStatus.UNKNOWN,
        command_args=ANDROID_IMPERSONATION,
        normalize_url=kuaishou_url,
        identity=ProviderIdentity.PREFER,
        cookie_domain_allowlist=frozenset({"kuaishou.com", "kuaishou.cn"}),
    ),
)
