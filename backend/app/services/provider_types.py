"""Provider capability and non-secret access context primitives."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Self

from app.services.provider_failures import FailureClass

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

    OPERATOR_MANAGED carries the dedicated platform login for one operation.
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


class ResolutionExecutionKind(StrEnum):
    HTTP = "http"
    BROWSER = "browser"


class ProviderSessionSource(StrEnum):
    NONE = "none"
    CHROME_SOURCE = "chrome_source"
    MANAGED_BROWSER = "managed_browser"


class MediaHandoff(StrEnum):
    HTTP_TRANSFERABLE = "http_transferable"
    BROWSER_TRANSFERABLE = "browser_transferable"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class ResolutionStrategy:
    strategy_id: str
    adapter_id: str
    adapter_revision: str
    execution_kind: ResolutionExecutionKind
    access_mode: ProviderAccessMode
    session_source: ProviderSessionSource
    context_requirements: tuple[str, ...]
    allowed_failure_classes: frozenset[FailureClass]
    media_handoff: MediaHandoff
    validator: str
    step_timeout_ms: int = 180_000
    enabled: bool = True

    def __post_init__(self) -> None:
        references = (
            self.strategy_id,
            self.adapter_id,
            self.adapter_revision,
            self.validator,
            *self.context_requirements,
        )
        if any(_REFERENCE.fullmatch(value) is None for value in references):
            raise ValueError("resolution strategy contains an invalid reference")
        if len(set(self.context_requirements)) != len(self.context_requirements):
            raise ValueError("resolution strategy repeats a context requirement")
        if not 0 < self.step_timeout_ms <= 180_000:
            raise ValueError("resolution strategy timeout is invalid")
        if self.access_mode is ProviderAccessMode.GUEST:
            raise ValueError("retired guest strategies cannot be declared")
        anonymous = self.access_mode is ProviderAccessMode.ANONYMOUS
        if anonymous != (self.session_source is ProviderSessionSource.NONE):
            raise ValueError("resolution strategy source does not match access mode")


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
    strategy_id: str | None = None
    adapter_revision: str | None = None
    session_source_id: str | None = None
    browser_context_revision: str | None = None
    protocol_capabilities: tuple[str, ...] = ()
    # None means no reliable public-egress observation, not a fixed public IP.
    egress_observation_ref: str | None = None

    def __post_init__(self) -> None:
        values = (
            self.provider_key,
            self.profile_version,
            self.egress_affinity_id,
            self.client_profile_id,
            self.engine_commit,
            self.runtime_revision,
        )
        optional = (
            self.credential_version_id,
            self.attestation_provider_version,
            self.strategy_id,
            self.adapter_revision,
            self.session_source_id,
            self.browser_context_revision,
            self.egress_observation_ref,
            *self.protocol_capabilities,
        )
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
        if (self.strategy_id is None) != (self.adapter_revision is None):
            raise ValueError("provider strategy revision is incomplete")
        if self.session_source_id is not None and not needs_context_material:
            raise ValueError("anonymous context cannot contain an account source")
        if self.strategy_id is None and any(
            (
                self.session_source_id,
                self.browser_context_revision,
                self.protocol_capabilities,
                self.egress_observation_ref,
            )
        ):
            raise ValueError("provider context requires a strategy identity")
        if self.strategy_id is not None and self.runtime_revision == "legacy":
            raise ValueError("provider strategy context requires a runtime revision")
        if (
            self.strategy_id is not None
            and needs_context_material
            and self.session_source_id is None
        ):
            raise ValueError("provider strategy context requires an account source")
        if not isinstance(self.protocol_capabilities, tuple):
            raise ValueError("provider protocols must be immutable")
        if len(set(self.protocol_capabilities)) != len(self.protocol_capabilities):
            raise ValueError("provider context repeats a protocol capability")
        object.__setattr__(
            self, "protocol_capabilities", tuple(sorted(self.protocol_capabilities))
        )

    def to_document(self) -> dict[str, object]:
        document: dict[str, object] = {
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
        if self.strategy_id is not None:
            document.update(
                strategy_id=self.strategy_id,
                adapter_revision=self.adapter_revision,
                session_source_id=self.session_source_id,
                browser_context_revision=self.browser_context_revision,
                protocol_capabilities=list(self.protocol_capabilities),
                egress_observation_ref=self.egress_observation_ref,
            )
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
        if self.strategy_id is not None:
            values += (
                json.dumps(
                    {
                        "strategy_id": self.strategy_id,
                        "adapter_revision": self.adapter_revision,
                        "session_source_id": self.session_source_id,
                        "browser_context_revision": self.browser_context_revision,
                        "protocol_capabilities": sorted(self.protocol_capabilities),
                        "egress_observation_ref": self.egress_observation_ref,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
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
        strategy_keys = {
            "strategy_id",
            "adapter_revision",
            "session_source_id",
            "browser_context_revision",
            "protocol_capabilities",
            "egress_observation_ref",
        }
        if set(value) not in (keys, keys - {"runtime_revision"}, keys | strategy_keys):
            raise ValueError("provider access context fields are invalid")

        def required(name: str) -> str:
            item = value[name]
            if not isinstance(item, str):
                raise ValueError("provider access context field is invalid")
            return item

        def optional(name: str) -> str | None:
            item = value.get(name)
            if item is not None and not isinstance(item, str):
                raise ValueError("provider access context field is invalid")
            return item

        protocols = value.get("protocol_capabilities", [])
        if not isinstance(protocols, list) or any(
            not isinstance(item, str) for item in protocols
        ):
            raise ValueError("provider protocols must be a list of references")
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
            strategy_id=optional("strategy_id"),
            adapter_revision=optional("adapter_revision"),
            session_source_id=optional("session_source_id"),
            browser_context_revision=optional("browser_context_revision"),
            protocol_capabilities=tuple(protocols),
            egress_observation_ref=optional("egress_observation_ref"),
        )
