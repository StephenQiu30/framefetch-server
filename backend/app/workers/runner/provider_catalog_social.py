"""Mainstream social and video provider profiles."""

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
    HeaderPlugin,
    SiteSessionPolicy,
)
from app.workers.runner.provider_factories import (
    CHROME_IMPERSONATION,
    standard_provider,
)
from app.workers.runner.provider_normalizers import vimeo_url, wechat_channels_url
from app.workers.runner.provider_registry import ProviderProfile

SOCIAL_PROVIDER_PROFILES: tuple[ProviderProfile, ...] = (
    standard_provider(
        ProviderKey.WECHAT_CHANNELS,
        "微信视频号",
        ("weixin.qq.com",),
        access_policy=ProviderAccessPolicy.OPERATOR_PUBLIC,
        session_policy=SiteSessionPolicy(
            "weixin.qq.com",
            ProviderKey.WECHAT_CHANNELS,
            "https://yuanbao.tencent.com/",
            required_cookie_names=frozenset({"hy_user", "hy_token"}),
            requirement=CookieRequirement.ALL,
            header_plugin=HeaderPlugin.YUANBAO,
        ),
        version=ProviderProfileVersion.WECHAT_CHANNELS,
        normalize_url=wechat_channels_url,
        capabilities=frozenset(
            {ProviderCapability.SINGLE_VIDEO, ProviderCapability.SHORT_VIDEO}
        ),
        status=ProviderSupportStatus.ACCESS_REQUIRED,
        operator_cookie_domains=frozenset({ProviderCookieDomain.YUANBAO}),
        command_args=CHROME_IMPERSONATION,
        client_profile_id="chrome-136-macos-15",
        canary_suite="wechat-channels-public-single-video",
        probe_authenticated_media=True,
        probe_media_duration=True,
    ),
    standard_provider(
        ProviderKey.VIMEO,
        "Vimeo",
        ("vimeo.com", "www.vimeo.com", "player.vimeo.com"),
        normalize_url=vimeo_url,
        status=ProviderSupportStatus.VERIFIED,
        command_args=("--check-formats",),
    ),
    standard_provider(
        ProviderKey.X,
        "X / Twitter",
        (
            "x.com",
            "www.x.com",
            "twitter.com",
            "www.twitter.com",
            "mobile.twitter.com",
        ),
        access_policy=ProviderAccessPolicy.OPERATOR_PUBLIC,
        session_policy=SiteSessionPolicy(
            "x.com",
            ProviderKey.X,
            "https://x.com/home",
            required_cookie_names=frozenset({"auth_token", "ct0"}),
            requirement=CookieRequirement.ALL,
        ),
        status=ProviderSupportStatus.VERIFIED,
        operator_cookie_domains=frozenset(
            {ProviderCookieDomain.X, ProviderCookieDomain.TWITTER}
        ),
        probe_authenticated_media=True,
    ),
    standard_provider(
        ProviderKey.INSTAGRAM,
        "Instagram",
        ("instagram.com", "www.instagram.com"),
        access_policy=ProviderAccessPolicy.OPERATOR_PUBLIC,
        session_policy=SiteSessionPolicy(
            "instagram.com",
            ProviderKey.INSTAGRAM,
            "https://www.instagram.com/",
            required_cookie_names=frozenset({"sessionid"}),
        ),
        status=ProviderSupportStatus.VERIFIED,
        operator_cookie_domains=frozenset({ProviderCookieDomain.INSTAGRAM}),
        probe_authenticated_media=True,
    ),
    standard_provider(
        ProviderKey.FACEBOOK,
        "Facebook",
        (
            "facebook.com",
            "www.facebook.com",
            "web.facebook.com",
            "m.facebook.com",
            "fb.watch",
        ),
        access_policy=ProviderAccessPolicy.OPERATOR_PUBLIC,
        session_policy=SiteSessionPolicy(
            "facebook.com",
            ProviderKey.FACEBOOK,
            "https://www.facebook.com/",
            required_cookie_names=frozenset({"c_user", "xs"}),
            requirement=CookieRequirement.ALL,
        ),
        version=ProviderProfileVersion.FACEBOOK,
        capabilities=frozenset(
            {
                ProviderCapability.SINGLE_VIDEO,
                ProviderCapability.SHORT_VIDEO,
                ProviderCapability.AUDIO_VIDEO_SPLIT,
            }
        ),
        status=ProviderSupportStatus.VERIFIED,
        operator_cookie_domains=frozenset({ProviderCookieDomain.FACEBOOK}),
        command_args=CHROME_IMPERSONATION,
        client_profile_id="chrome-136-macos-15",
        canary_suite="facebook-public-reel-single-video",
        probe_authenticated_media=True,
    ),
    standard_provider(
        ProviderKey.TWITCH,
        "Twitch",
        ("twitch.tv", "www.twitch.tv", "clips.twitch.tv"),
        version=ProviderProfileVersion.TWITCH,
        capabilities=frozenset(
            {ProviderCapability.SINGLE_VIDEO, ProviderCapability.CLIP_OR_VOD}
        ),
        status=ProviderSupportStatus.VERIFIED,
        canary_suite="twitch-public-clip",
    ),
    standard_provider(
        ProviderKey.REDDIT,
        "Reddit",
        ("reddit.com", "www.reddit.com", "old.reddit.com", "redd.it"),
        access_policy=ProviderAccessPolicy.OPERATOR_PUBLIC,
        session_policy=SiteSessionPolicy(
            "reddit.com",
            ProviderKey.REDDIT,
            "https://www.reddit.com/",
            # ``loid`` is Reddit's logged-out visitor id.
            required_cookie_names=frozenset({"reddit_session"}),
        ),
        version=ProviderProfileVersion.REDDIT,
        capabilities=frozenset({ProviderCapability.SINGLE_VIDEO}),
        status=ProviderSupportStatus.ACCESS_REQUIRED,
        operator_cookie_domains=frozenset({ProviderCookieDomain.REDDIT}),
        canary_suite="reddit-anonymous-operator-video",
    ),
)
