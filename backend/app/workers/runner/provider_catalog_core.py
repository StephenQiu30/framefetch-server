"""Core and browser-challenged provider profiles."""

from __future__ import annotations

from app.services.provider_types import (
    ProviderAccessMode,
    ProviderCapability,
    ProviderCookieDomain,
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
        access_modes=(
            ProviderAccessMode.ANONYMOUS,
            ProviderAccessMode.OPERATOR_MANAGED,
        ),
        cookie_domain_allowlist=frozenset(
            {
                ProviderCookieDomain.YOUTUBE,
                ProviderCookieDomain.YOUTUBE_NOCOOKIE,
            }
        ),
        client_profile_id="youtube-mweb",
        attestation_policy="bgutil-mweb-player-gvs",
        egress_pool="youtube-sticky",
        credential_concurrency=1,
        support_status=ProviderSupportStatus.ACCESS_REQUIRED,
        canary_suite="youtube-anonymous-operator-pot",
        runtime_command_args=_youtube_runtime_args,
        yt_dlp_retry_count=0,
        inspection_attempts=1,
    ),
    standard_provider(
        ProviderKey.BILIBILI,
        "哔哩哔哩",
        ("bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv"),
        status=ProviderSupportStatus.VERIFIED,
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
        status=ProviderSupportStatus.ACCESS_REQUIRED,
        operator_cookie_domains=frozenset(
            {ProviderCookieDomain.DOUYIN, ProviderCookieDomain.DOUYIN_MEDIA}
        ),
        canary_suite="douyin-anonymous-operator-video",
        probe_authenticated_media=True,
        probe_media_duration=True,
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
        status=ProviderSupportStatus.VERIFIED,
        client_profile_id="yt-dlp-default",
        canary_suite="tiktok-public-player-video",
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
        status=ProviderSupportStatus.DEGRADED,
        operator_cookie_domains=frozenset({ProviderCookieDomain.XIAOHONGSHU}),
        canary_suite="xiaohongshu-anonymous-operator-video",
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
        client_profile_id="chrome-131-android-14",
        support_status=ProviderSupportStatus.VERIFIED,
        canary_suite="kuaishou-public-share-page",
        command_args=ANDROID_IMPERSONATION,
        inspection_attempts=4,
        inspection_retry_delay=0.5,
        normalize_url=kuaishou_url,
    ),
)
