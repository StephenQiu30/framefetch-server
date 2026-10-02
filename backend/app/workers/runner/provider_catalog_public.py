"""Public single-media provider profiles."""

from app.services.provider_types import (
    ProviderCapability,
    ProviderCookieDomain,
    ProviderIdentity,
    ProviderKey,
    ProviderProfileVersion,
    ProviderSupportStatus,
)
from app.workers.runner.provider_factories import (
    CHROME_IMPERSONATION,
    standard_provider,
)
from app.workers.runner.provider_normalizers import (
    dailymotion_url,
    hongguo_url,
    kick_url,
    linkedin_url,
    qqvideo_url,
    snapchat_url,
    telegram_url,
    tumblr_url,
    weibo_url,
)
from app.workers.runner.provider_registry import ProviderProfile

SINGLE_VIDEO = frozenset({ProviderCapability.SINGLE_VIDEO})

PUBLIC_PROVIDER_PROFILES: tuple[ProviderProfile, ...] = (
    standard_provider(
        ProviderKey.DAILYMOTION,
        "Dailymotion",
        ("dailymotion.com", "www.dailymotion.com", "dai.ly"),
        version=ProviderProfileVersion.DAILYMOTION,
        normalize_url=dailymotion_url,
        capabilities=SINGLE_VIDEO,
        status=ProviderSupportStatus.UNKNOWN,
        command_args=("--abort-on-unavailable-fragments",),
    ),
    standard_provider(
        ProviderKey.PINTEREST,
        "Pinterest",
        ("pinterest.com", "www.pinterest.com", "pin.it"),
        version=ProviderProfileVersion.PINTEREST,
        capabilities=SINGLE_VIDEO,
        status=ProviderSupportStatus.UNKNOWN,
    ),
    standard_provider(
        ProviderKey.WEIBO,
        "微博",
        (
            "weibo.com",
            "www.weibo.com",
            "weibo.cn",
            "m.weibo.cn",
            "video.weibo.com",
            "t.cn",
        ),
        version=ProviderProfileVersion.WEIBO,
        normalize_url=weibo_url,
        capabilities=SINGLE_VIDEO,
        status=ProviderSupportStatus.UNKNOWN,
        identity=ProviderIdentity.PREFER,
        cookie_domain_allowlist=frozenset({"weibo.com", "weibo.cn"}),
    ),
    standard_provider(
        ProviderKey.YOUKU,
        "优酷",
        ("youku.com", "www.youku.com", "v.youku.com"),
        version=ProviderProfileVersion.YOUKU,
        content_scope="personal_full",
        capabilities=SINGLE_VIDEO,
        status=ProviderSupportStatus.UNKNOWN,
        cookie_domain_allowlist=frozenset({ProviderCookieDomain.YOUKU}),
        probe_authenticated_media=True,
        identity=ProviderIdentity.REQUIRED,
    ),
    standard_provider(
        ProviderKey.QQVIDEO,
        "腾讯视频",
        ("v.qq.com",),
        version=ProviderProfileVersion.QQVIDEO,
        content_scope="personal_full",
        capabilities=SINGLE_VIDEO,
        status=ProviderSupportStatus.UNKNOWN,
        normalize_url=qqvideo_url,
        cookie_domain_allowlist=frozenset({ProviderCookieDomain.QQVIDEO}),
        probe_authenticated_media=True,
        command_args=(
            "--socket-timeout",
            "10",
            "--concurrent-fragments",
            "4",
        ),
        identity=ProviderIdentity.REQUIRED,
    ),
    standard_provider(
        ProviderKey.SNAPCHAT,
        "Snapchat Spotlight",
        ("snapchat.com", "www.snapchat.com"),
        version=ProviderProfileVersion.SNAPCHAT,
        normalize_url=snapchat_url,
        capabilities=frozenset(
            {ProviderCapability.SINGLE_VIDEO, ProviderCapability.SHORT_VIDEO}
        ),
        status=ProviderSupportStatus.UNKNOWN,
    ),
    standard_provider(
        ProviderKey.LINKEDIN,
        "LinkedIn",
        ("linkedin.com", "www.linkedin.com"),
        version=ProviderProfileVersion.LINKEDIN,
        normalize_url=linkedin_url,
        capabilities=SINGLE_VIDEO,
        status=ProviderSupportStatus.UNKNOWN,
    ),
    standard_provider(
        ProviderKey.TELEGRAM,
        "Telegram",
        ("t.me",),
        version=ProviderProfileVersion.TELEGRAM,
        normalize_url=telegram_url,
        capabilities=SINGLE_VIDEO,
        status=ProviderSupportStatus.UNKNOWN,
    ),
    standard_provider(
        ProviderKey.KICK,
        "Kick",
        ("kick.com", "www.kick.com"),
        version=ProviderProfileVersion.KICK,
        normalize_url=kick_url,
        capabilities=frozenset(
            {ProviderCapability.SINGLE_VIDEO, ProviderCapability.CLIP_OR_VOD}
        ),
        status=ProviderSupportStatus.UNKNOWN,
    ),
    standard_provider(
        ProviderKey.TUMBLR,
        "Tumblr",
        ("tumblr.com", "www.tumblr.com"),
        version=ProviderProfileVersion.TUMBLR,
        normalize_url=tumblr_url,
        host_suffixes=frozenset({"tumblr.com"}),
        capabilities=SINGLE_VIDEO,
        status=ProviderSupportStatus.UNKNOWN,
        command_args=CHROME_IMPERSONATION,
        client_profile="chrome-136-macos-15",
    ),
    ProviderProfile(
        key=ProviderKey.HONGGUO_WEB,
        display_name="红果短剧官方分享",
        hosts=frozenset({"novelquickapp.com", "hongguoduanju.com"}),
        version=ProviderProfileVersion.HONGGUO_WEB,
        normalize_url=hongguo_url,
        capabilities=SINGLE_VIDEO,
        support_status=ProviderSupportStatus.UNKNOWN,
        # The supported official web share is anonymous. ttwid is a visitor
        # identifier, not account material; no verified login route is declared.
        identity=ProviderIdentity.NONE,
    ),
)
