"""Provider capability and non-secret access context primitives."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
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


class ProviderAccessMode(StrEnum):
    """Privilege boundary for one provider operation.

    OPERATOR_MANAGED carries the operator's own Chrome login for one operation.
    GUEST only appears in persisted history from the retired visitor route.
    """

    ANONYMOUS = "anonymous"
    GUEST = "guest"
    OPERATOR_MANAGED = "operator_managed"


class ProviderCapability(StrEnum):
    SINGLE_VIDEO = "single_video"
    SHORT_VIDEO = "short_video"
    CLIP_OR_VOD = "clip_or_vod"
    AUDIO_VIDEO_SPLIT = "audio_video_split"
    SUBTITLES = "subtitles"
    IMAGE_OR_CAROUSEL = "image_or_carousel"
    LIVE = "live"
    PLAYLIST = "playlist"


class ProviderSupportStatus(StrEnum):
    UNKNOWN = "unknown"
    VERIFIED = "verified"
    DEGRADED = "degraded"
    ACCESS_REQUIRED = "access_required"
    RATE_LIMITED = "rate_limited"
    BLOCKED = "blocked"
    DISABLED = "disabled"
    UNSUPPORTED = "unsupported"


class ProviderAccessState(StrEnum):
    """User-facing access state projected from support and runtime evidence."""

    PUBLIC_PROBE = "public_probe"
    PUBLIC_READY = "public_ready"
    AUTHORIZATION_REQUIRED = "authorization_required"
    OPERATOR_PROBE = "operator_probe"
    OPERATOR_READY = "operator_ready"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    DISABLED = "disabled"
    UNSUPPORTED = "unsupported"


class ProviderCanaryStage(StrEnum):
    METADATA = "metadata"
    MEDIA = "media"
    ANALYSIS = "analysis"


class ProviderCanaryOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ProviderCanaryResult:
    target_id: str
    provider_key: str
    profile_version: str
    stage: ProviderCanaryStage
    access_mode: ProviderAccessMode
    outcome: ProviderCanaryOutcome
    checked_at: datetime
    duration_ms: int
    engine_commit: str
    egress_affinity_id: str
    client_profile_id: str
    context_generation_id: str
    stable_error_code: str | None = None

    def __post_init__(self) -> None:
        references = (
            self.target_id,
            self.provider_key,
            self.profile_version,
            self.engine_commit,
            self.egress_affinity_id,
            self.client_profile_id,
            self.context_generation_id,
        )
        if any(_REFERENCE.fullmatch(value) is None for value in references):
            raise ValueError("provider canary contains an invalid reference")
        if self.checked_at.tzinfo is None or self.duration_ms < 0:
            raise ValueError("provider canary timing is invalid")
        failed = self.outcome is ProviderCanaryOutcome.FAILED
        if failed != (self.stable_error_code is not None):
            raise ValueError("provider canary error does not match outcome")
        if self.stable_error_code is not None and (
            _REFERENCE.fullmatch(self.stable_error_code) is None
        ):
            raise ValueError("provider canary error code is invalid")


@dataclass(frozen=True, slots=True)
class ProviderAccessContextRef:
    """Immutable references needed to reproduce provider access safely."""

    provider_key: str
    profile_version: str
    access_mode: ProviderAccessMode
    credential_version_id: str | None
    egress_affinity_id: str
    client_profile_id: str
    attestation_provider_version: str | None
    engine_commit: str
    # Historical records have no release digest and cannot match a new Runner.
    runtime_revision: str = "legacy"

    def __post_init__(self) -> None:
        values = (
            self.provider_key,
            self.profile_version,
            self.egress_affinity_id,
            self.client_profile_id,
            self.engine_commit,
            self.runtime_revision,
        )
        optional = (self.credential_version_id, self.attestation_provider_version)
        if any(_REFERENCE.fullmatch(value) is None for value in values):
            raise ValueError("provider access context contains an invalid reference")
        if any(
            value is not None and _REFERENCE.fullmatch(value) is None
            for value in optional
        ):
            raise ValueError("provider access context contains an invalid reference")
        has_context_material = self.credential_version_id is not None
        needs_context_material = self.access_mode is not ProviderAccessMode.ANONYMOUS
        if has_context_material != needs_context_material:
            raise ValueError("provider credential reference does not match access mode")

    def to_document(self) -> dict[str, str | None]:
        document = {
            "provider_key": self.provider_key,
            "profile_version": self.profile_version,
            "access_mode": self.access_mode.value,
            "credential_version_id": self.credential_version_id,
            "egress_affinity_id": self.egress_affinity_id,
            "client_profile_id": self.client_profile_id,
            "attestation_provider_version": self.attestation_provider_version,
            "engine_commit": self.engine_commit,
        }
        if self.runtime_revision != "legacy":
            document["runtime_revision"] = self.runtime_revision
        return document

    @property
    def generation_id(self) -> str:
        """Stable identity for every non-secret input that defines a route."""
        values: tuple[str, ...] = (
            self.provider_key,
            self.profile_version,
            self.access_mode.value,
            self.credential_version_id or "",
            self.egress_affinity_id,
            self.client_profile_id,
            self.attestation_provider_version or "",
            self.engine_commit,
        )
        if self.runtime_revision != "legacy":
            values += (self.runtime_revision,)
        return sha256("\x1f".join(values).encode()).hexdigest()

    @classmethod
    def from_document(cls, value: object) -> Self:
        if not isinstance(value, dict):
            raise ValueError("provider access context must be an object")
        keys = {
            "provider_key",
            "profile_version",
            "access_mode",
            "credential_version_id",
            "egress_affinity_id",
            "client_profile_id",
            "attestation_provider_version",
            "engine_commit",
            "runtime_revision",
        }
        if set(value) not in (keys, keys - {"runtime_revision"}):
            raise ValueError("provider access context fields are invalid")

        def required(name: str) -> str:
            item = value[name]
            if not isinstance(item, str):
                raise ValueError("provider access context field is invalid")
            return item

        def optional(name: str) -> str | None:
            item = value[name]
            if item is not None and not isinstance(item, str):
                raise ValueError("provider access context field is invalid")
            return item

        return cls(
            provider_key=required("provider_key"),
            profile_version=required("profile_version"),
            access_mode=ProviderAccessMode(required("access_mode")),
            credential_version_id=optional("credential_version_id"),
            egress_affinity_id=required("egress_affinity_id"),
            client_profile_id=required("client_profile_id"),
            attestation_provider_version=optional("attestation_provider_version"),
            engine_commit=required("engine_commit"),
            runtime_revision=(
                required("runtime_revision")
                if "runtime_revision" in value
                else "legacy"
            ),
        )
