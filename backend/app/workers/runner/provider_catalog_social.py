"""Mainstream social and video provider profiles."""

from app.services.provider_types import (
    ProviderCapability,
    ProviderCookieDomain,
    ProviderIdentity,
    ProviderKey,
    ProviderProfileVersion,
    ProviderSupportStatus,
)
from app.workers.identity.yuanbao_parse import YUANBAO_ORIGIN
from app.workers.runner.provider_factories import (
    CHROME_IMPERSONATION,
    standard_provider,
)
from app.workers.runner.provider_normalizers import vimeo_url, wechat_channels_url
from app.workers.runner.provider_registry import ProviderProfile

SOCIAL_PROVIDER_PROFILES: tuple[ProviderProfile, ...] = (
    ProviderProfile(
        ProviderKey.WECHAT_CHANNELS,
        "微信视频号",
        frozenset({"weixin.qq.com"}),
        version=ProviderProfileVersion.WECHAT_CHANNELS,
        normalize_url=wechat_channels_url,
        capabilities=frozenset(
            {ProviderCapability.SINGLE_VIDEO, ProviderCapability.SHORT_VIDEO}
        ),
        support_status=ProviderSupportStatus.UNKNOWN,
        # The existing Chrome page supplies its own native authenticated request.
        identity_source="yuanbao_native",
        identity_origin=YUANBAO_ORIGIN,
        command_args=CHROME_IMPERSONATION,
        client_profile="chrome-136-macos-15",
        probe_authenticated_media=True,
        probe_media_duration=True,
        identity=ProviderIdentity.REQUIRED,
    ),
    standard_provider(
        ProviderKey.VIMEO,
        "Vimeo",
        ("vimeo.com", "www.vimeo.com", "player.vimeo.com"),
        normalize_url=vimeo_url,
        status=ProviderSupportStatus.UNKNOWN,
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
        status=ProviderSupportStatus.UNKNOWN,
        cookie_domain_allowlist=frozenset(
            {ProviderCookieDomain.X, ProviderCookieDomain.TWITTER}
        ),
        probe_authenticated_media=True,
        identity=ProviderIdentity.PREFER,
    ),
    standard_provider(
        ProviderKey.INSTAGRAM,
        "Instagram",
        ("instagram.com", "www.instagram.com"),
        status=ProviderSupportStatus.UNKNOWN,
        cookie_domain_allowlist=frozenset({ProviderCookieDomain.INSTAGRAM}),
        probe_authenticated_media=True,
        identity=ProviderIdentity.REQUIRED,
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
        version=ProviderProfileVersion.FACEBOOK,
        capabilities=frozenset(
            {
                ProviderCapability.SINGLE_VIDEO,
                ProviderCapability.SHORT_VIDEO,
                ProviderCapability.AUDIO_VIDEO_SPLIT,
            }
        ),
        status=ProviderSupportStatus.UNKNOWN,
        cookie_domain_allowlist=frozenset({ProviderCookieDomain.FACEBOOK}),
        command_args=CHROME_IMPERSONATION,
        client_profile="chrome-136-macos-15",
        probe_authenticated_media=True,
        identity=ProviderIdentity.PREFER,
    ),
    standard_provider(
        ProviderKey.TWITCH,
        "Twitch",
        ("twitch.tv", "www.twitch.tv", "clips.twitch.tv"),
        version=ProviderProfileVersion.TWITCH,
        capabilities=frozenset(
            {ProviderCapability.SINGLE_VIDEO, ProviderCapability.CLIP_OR_VOD}
        ),
        status=ProviderSupportStatus.UNKNOWN,
    ),
    standard_provider(
        ProviderKey.REDDIT,
        "Reddit",
        ("reddit.com", "www.reddit.com", "old.reddit.com", "redd.it"),
        version=ProviderProfileVersion.REDDIT,
        capabilities=frozenset({ProviderCapability.SINGLE_VIDEO}),
        status=ProviderSupportStatus.UNKNOWN,
        cookie_domain_allowlist=frozenset({ProviderCookieDomain.REDDIT}),
        identity=ProviderIdentity.PREFER,
    ),
)
