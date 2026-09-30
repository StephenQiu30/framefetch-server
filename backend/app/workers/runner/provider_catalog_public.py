"""Public single-media provider profiles."""

from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_types import (
    ProviderCapability,
    ProviderCookieDomain,
    ProviderKey,
    ProviderProfileVersion,
    ProviderSupportStatus,
)
from app.services.site_sessions import (
    CookieRequirement,
    SessionEntitlement,
    SiteSessionPolicy,
)
from app.workers.runner.provider_factories import (
    CHROME_IMPERSONATION,
    standard_provider,
)
from app.workers.runner.provider_normalizers import (
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
        ProviderKey.PINTEREST,
        "Pinterest",
        ("pinterest.com", "www.pinterest.com", "pin.it"),
        access_policy=ProviderAccessPolicy.OPERATOR_PUBLIC,
        session_policy=SiteSessionPolicy(
            "pinterest.com",
            ProviderKey.PINTEREST,
            "https://www.pinterest.com/",
            required_cookie_names=frozenset({"_auth", "_pinterest_sess"}),
            requirement=CookieRequirement.ALL,
        ),
        version=ProviderProfileVersion.PINTEREST,
        capabilities=SINGLE_VIDEO,
        status=ProviderSupportStatus.VERIFIED,
        operator_cookie_domains=frozenset({ProviderCookieDomain.PINTEREST}),
        canary_suite="pinterest-public-video-pin",
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
        status=ProviderSupportStatus.VERIFIED,
        canary_suite="weibo-public-single-video",
    ),
    standard_provider(
        ProviderKey.YOUKU,
        "优酷",
        ("youku.com", "www.youku.com", "v.youku.com"),
        access_policy=ProviderAccessPolicy.PERSONAL_ENTITLED,
        session_policy=SiteSessionPolicy(
            "youku.com",
            ProviderKey.YOUKU,
            "https://www.youku.com/",
            entitlement=SessionEntitlement.ACCOUNT_ENTITLED_FULL_VIDEO,
            required_cookie_names=frozenset({"P_sck"}),
        ),
        version=ProviderProfileVersion.YOUKU,
        capabilities=SINGLE_VIDEO,
        status=ProviderSupportStatus.UNKNOWN,
        operator_cookie_domains=frozenset({ProviderCookieDomain.YOUKU}),
        canary_suite="youku-public-single-video",
    ),
    standard_provider(
        ProviderKey.QQVIDEO,
        "腾讯视频",
        ("v.qq.com",),
        access_policy=ProviderAccessPolicy.PERSONAL_ENTITLED,
        session_policy=SiteSessionPolicy(
            "v.qq.com",
            ProviderKey.QQVIDEO,
            "https://v.qq.com/",
            entitlement=SessionEntitlement.ACCOUNT_ENTITLED_FULL_VIDEO,
            required_cookie_names=frozenset({"v_vuserid", "v_vusession"}),
            requirement=CookieRequirement.ALL,
        ),
        version=ProviderProfileVersion.QQVIDEO,
        capabilities=SINGLE_VIDEO,
        status=ProviderSupportStatus.UNKNOWN,
        normalize_url=qqvideo_url,
        operator_cookie_domains=frozenset({ProviderCookieDomain.QQVIDEO}),
        probe_authenticated_media=True,
        command_args=(
            "--socket-timeout",
            "10",
            "--concurrent-fragments",
            "4",
        ),
        canary_suite="qqvideo-personal-single-video",
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
        status=ProviderSupportStatus.VERIFIED,
        canary_suite="snapchat-public-spotlight",
    ),
    standard_provider(
        ProviderKey.LINKEDIN,
        "LinkedIn",
        ("linkedin.com", "www.linkedin.com"),
        version=ProviderProfileVersion.LINKEDIN,
        normalize_url=linkedin_url,
        capabilities=SINGLE_VIDEO,
        status=ProviderSupportStatus.VERIFIED,
        canary_suite="linkedin-public-single-video-post",
    ),
    standard_provider(
        ProviderKey.TELEGRAM,
        "Telegram",
        ("t.me",),
        version=ProviderProfileVersion.TELEGRAM,
        normalize_url=telegram_url,
        capabilities=SINGLE_VIDEO,
        status=ProviderSupportStatus.VERIFIED,
        canary_suite="telegram-public-channel-single-video",
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
        status=ProviderSupportStatus.VERIFIED,
        canary_suite="kick-public-clip",
    ),
    standard_provider(
        ProviderKey.TUMBLR,
        "Tumblr",
        ("tumblr.com", "www.tumblr.com"),
        version=ProviderProfileVersion.TUMBLR,
        normalize_url=tumblr_url,
        host_suffixes=frozenset({"tumblr.com"}),
        capabilities=SINGLE_VIDEO,
        status=ProviderSupportStatus.VERIFIED,
        command_args=CHROME_IMPERSONATION,
        client_profile_id="chrome-136-macos-15",
        canary_suite="tumblr-public-single-video-post",
    ),
    ProviderProfile(
        key=ProviderKey.HONGGUO_WEB,
        display_name="红果短剧官方分享",
        hosts=frozenset({"novelquickapp.com", "hongguoduanju.com"}),
        version=ProviderProfileVersion.HONGGUO_WEB,
        normalize_url=hongguo_url,
        capabilities=SINGLE_VIDEO,
        support_status=ProviderSupportStatus.VERIFIED,
        canary_suite="hongguo-official-share-single-video",
    ),
)
