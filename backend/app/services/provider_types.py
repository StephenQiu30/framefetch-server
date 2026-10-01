"""Provider capability and non-secret access context primitives."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from ipaddress import ip_address
from typing import Self

_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


class ProviderKey(StrEnum):
    GENERIC = "generic"
    YOUTUBE = "youtube"
    BILIBILI = "bilibili"
    DOUYIN = "douyin"
    TIKTOK = "tiktok"
    XIAOHONGSHU = "xiaohongshu"
    KUAISHOU = "kuaishou"
    WECHAT_CHANNELS = "wechat_channels"
    VIMEO = "vimeo"
    X = "x"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    TWITCH = "twitch"
    REDDIT = "reddit"
    PINTEREST = "pinterest"
    WEIBO = "weibo"
    YOUKU = "youku"
    QQVIDEO = "qqvideo"
    SNAPCHAT = "snapchat"
    LINKEDIN = "linkedin"
    TELEGRAM = "telegram"
    KICK = "kick"
    TUMBLR = "tumblr"
    HONGGUO_WEB = "hongguo_web"
    PEERTUBE = "peertube"
    WECHAT_OFFICIAL_ACCOUNT_ARTICLE = "wechat_official_account_article"


class ProviderProfileVersion(StrEnum):
    DEFAULT = "default"
    YOUTUBE = "youtube"
    BILIBILI = "bilibili-public"
    DOUYIN = "douyin-public"
    TIKTOK = "tiktok-public-player"
    XIAOHONGSHU = "xiaohongshu-public"
    KUAISHOU = "kuaishou-public"
    WECHAT_CHANNELS = "wechat-channels-public"
    VIMEO = "vimeo-public"
    X = "x-public"
    INSTAGRAM = "instagram-public"
    FACEBOOK = "facebook-public-reel"
    TWITCH = "twitch-public-clip"
    REDDIT = "reddit-public-video"
    PINTEREST = "pinterest-public-video-pin"
    WEIBO = "weibo-public-video"
    YOUKU = "youku-personal-v1"
    QQVIDEO = "qqvideo-personal-v1"
    SNAPCHAT = "snapchat-spotlight"
    LINKEDIN = "linkedin-public-post"
    TELEGRAM = "telegram-public-channel-post"
    KICK = "kick-public-clip"
    TUMBLR = "tumblr-public-video-post"
    HONGGUO_WEB = "hongguo-official-share"
    PEERTUBE = "peertube-approved-instance"


class ProviderCookieDomain(StrEnum):
    YOUTUBE = "youtube.com"
    YOUTUBE_NOCOOKIE = "youtube-nocookie.com"
    DOUYIN = "douyin.com"
    DOUYIN_MEDIA = "iesdouyin.com"
    XIAOHONGSHU = "xiaohongshu.com"
    X = "x.com"
    TWITTER = "twitter.com"
    INSTAGRAM = "instagram.com"
    FACEBOOK = "facebook.com"
    REDDIT = "reddit.com"
    PINTEREST = "pinterest.com"
    YUANBAO = "yuanbao.tencent.com"
    YOUKU = "youku.com"
    QQVIDEO = "v.qq.com"


class ProviderCapability(StrEnum):
    SINGLE_VIDEO = "single_video"
    SHORT_VIDEO = "short_video"
    CLIP_OR_VOD = "clip_or_vod"
    AUDIO_VIDEO_SPLIT = "audio_video_split"
    SUBTITLES = "subtitles"
    IMAGE_OR_CAROUSEL = "image_or_carousel"
    LIVE = "live"
    PLAYLIST = "playlist"


class Layer(StrEnum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class EgressRoute(StrEnum):
    CN = "cn_residential"
    GLOBAL = "global_residential"
    BY_DOMAIN = "by_domain"


@dataclass(frozen=True, slots=True)
class PrepareSpec:
    """Proof preparation declared here and implemented in R2."""

    kind: str
    clients: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BrowserRules:
    """Platform parser and interception patterns, implemented in R3."""

    platform: str
    response_patterns: tuple[str, ...] = ()


class ProviderIdentity(StrEnum):
    NONE = "none"
    PREFER = "prefer"
    REQUIRED = "required"


class ProviderSupportStatus(StrEnum):
    UNKNOWN = "unknown"
    DISABLED = "disabled"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """The twelve non-secret facts needed to reproduce a media execution."""

    provider_key: str
    registry_revision: str
    resolved_layer: str
    client: str
    engine_revision: str
    egress_route: str
    egress_revision: str
    egress_class: str
    egress_observed_ip: str | None
    identity_used: bool
    identity_digest: str | None
    browser_context_kind: str

    def __post_init__(self) -> None:
        references = (
            self.provider_key,
            self.registry_revision,
            self.client,
            self.engine_revision,
            self.egress_route,
            self.egress_revision,
        )
        if any(
            not isinstance(value, str) or _REFERENCE.fullmatch(value) is None
            for value in references
        ):
            raise ValueError("execution context contains an invalid reference")
        if self.resolved_layer not in {"L1", "L2", "L3"}:
            raise ValueError("execution context layer is invalid")
        if self.egress_class not in {"unknown", "residential", "datacenter"}:
            raise ValueError("execution egress class is invalid")
        if self.egress_observed_ip is not None:
            if (
                not isinstance(self.egress_observed_ip, str)
                or "%" in self.egress_observed_ip
            ):
                raise ValueError("execution egress IP is invalid")
            try:
                ip_address(self.egress_observed_ip)
            except ValueError as exc:
                raise ValueError("execution egress IP is invalid") from exc
        if not isinstance(self.identity_used, bool):
            raise ValueError("execution identity flag is invalid")
        if self.identity_used:
            if (
                not isinstance(self.identity_digest, str)
                or _REFERENCE.fullmatch(self.identity_digest) is None
            ):
                raise ValueError("execution identity digest is invalid")
        elif self.identity_digest is not None:
            raise ValueError("anonymous execution cannot contain an identity digest")
        if self.browser_context_kind not in {"none", "anonymous", "authenticated"}:
            raise ValueError("execution browser context kind is invalid")
        if self.browser_context_kind != "none" and (
            self.resolved_layer != "L3"
            or (self.browser_context_kind == "authenticated") != self.identity_used
        ):
            raise ValueError("execution browser context does not match its identity")

    def to_document(self) -> dict[str, object]:
        return {
            "provider_key": self.provider_key,
            "registry_revision": self.registry_revision,
            "resolved_layer": self.resolved_layer,
            "client": self.client,
            "engine_revision": self.engine_revision,
            "egress_route": self.egress_route,
            "egress_revision": self.egress_revision,
            "egress_class": self.egress_class,
            "egress_observed_ip": self.egress_observed_ip,
            "identity_used": self.identity_used,
            "identity_digest": self.identity_digest,
            "browser_context_kind": self.browser_context_kind,
        }

    @classmethod
    def from_document(cls, value: object) -> Self:
        fields = {
            "provider_key",
            "registry_revision",
            "resolved_layer",
            "client",
            "engine_revision",
            "egress_route",
            "egress_revision",
            "egress_class",
            "egress_observed_ip",
            "identity_used",
            "identity_digest",
            "browser_context_kind",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise ValueError("execution context fields are invalid")

        def required(name: str) -> str:
            item = value[name]
            if not isinstance(item, str):
                raise ValueError("execution context reference is invalid")
            return item

        def optional(name: str) -> str | None:
            item = value[name]
            if item is not None and not isinstance(item, str):
                raise ValueError("execution context reference is invalid")
            return item

        identity_used = value["identity_used"]
        if not isinstance(identity_used, bool):
            raise ValueError("execution identity flag is invalid")
        return cls(
            provider_key=required("provider_key"),
            registry_revision=required("registry_revision"),
            resolved_layer=required("resolved_layer"),
            client=required("client"),
            engine_revision=required("engine_revision"),
            egress_route=required("egress_route"),
            egress_revision=required("egress_revision"),
            egress_class=required("egress_class"),
            egress_observed_ip=optional("egress_observed_ip"),
            identity_used=identity_used,
            identity_digest=optional("identity_digest"),
            browser_context_kind=required("browser_context_kind"),
        )
