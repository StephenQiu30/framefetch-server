"""Public, non-secret Provider capability views."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_types import (
    ProviderAccessContextRef,
    ProviderAccessMode,
    ProviderAccessState,
    ProviderCapability,
    ProviderKey,
    ProviderSupportStatus,
)

YOUKU_DOWNLOAD_ACTION = (
    "公开单视频可直接解析；个人会话线路支持尝试获取账号可访问的完整非 DRM 内容。"
    "VIP 实际可用性待样本验证，试看或加密内容不会作为完整视频交付。"
)
QQVIDEO_DOWNLOAD_ACTION = (
    "普通单视频可直接解析，VIP 内容需要部署者配置有效持久会话。"
    "仅处理完整非 DRM 媒体，VIP 下载仍待账号样本验证。"
)


class ProviderEvidenceState(StrEnum):
    MISSING = "missing"
    STALE = "stale"
    FRESH = "fresh"


@dataclass(frozen=True, slots=True)
class ProviderAccessPolicyView:
    id: ProviderAccessPolicy
    configured: bool


@dataclass(frozen=True, slots=True)
class ProviderStatusView:
    key: str
    display_name: str
    profile_version: str | None
    registered: bool
    extractor_exists: bool
    capabilities: tuple[ProviderCapability, ...]
    access_modes: tuple[ProviderAccessMode, ...]
    status: ProviderSupportStatus
    last_checked_at: datetime | None
    last_check_succeeded: bool | None
    download_available: bool
    last_media_verified_at: datetime | None
    last_verified_at: datetime | None
    user_action: str | None
    access_policies: tuple[ProviderAccessPolicyView, ...] = ()
    default_access_policy_id: ProviderAccessPolicy | None = None
    evidence_state: ProviderEvidenceState = ProviderEvidenceState.MISSING
    hosts: tuple[str, ...] = ()
    host_suffixes: tuple[str, ...] = ()
    runtime_context: ProviderAccessContextRef | None = None
    route_retry_at: datetime | None = None

    @property
    def download_supported(self) -> bool:
        downloadable = {
            ProviderCapability.SINGLE_VIDEO,
            ProviderCapability.SHORT_VIDEO,
            ProviderCapability.CLIP_OR_VOD,
        }
        return (
            self.registered
            and self.extractor_exists
            and self.status
            not in {
                ProviderSupportStatus.DISABLED,
                ProviderSupportStatus.UNSUPPORTED,
            }
            and bool(downloadable.intersection(self.capabilities))
        )

    @property
    def access_state(self) -> ProviderAccessState:
        """Project internal evidence into one actionable public state."""
        access_mode = self._selected_access_mode()
        if self.status is ProviderSupportStatus.DISABLED:
            return ProviderAccessState.DISABLED
        if self.status is ProviderSupportStatus.UNSUPPORTED:
            return ProviderAccessState.UNSUPPORTED
        if self.status is ProviderSupportStatus.ACCESS_REQUIRED:
            return ProviderAccessState.AUTHORIZATION_REQUIRED
        if self.status is ProviderSupportStatus.BLOCKED:
            return ProviderAccessState.BLOCKED
        if self.status in {
            ProviderSupportStatus.DEGRADED,
            ProviderSupportStatus.RATE_LIMITED,
        }:
            return ProviderAccessState.DEGRADED
        # Historical analysis success is diagnostic evidence, not current media
        # availability. A release-verified profile must still have fresh media
        # evidence for its selected route before it is shown as ready.
        ready = (
            self.status is ProviderSupportStatus.VERIFIED and self.download_available
        )
        if access_mode is ProviderAccessMode.OPERATOR_MANAGED:
            if ready:
                return ProviderAccessState.OPERATOR_READY
            return ProviderAccessState.OPERATOR_PROBE
        if ready:
            return ProviderAccessState.PUBLIC_READY
        return ProviderAccessState.PUBLIC_PROBE

    def _selected_access_mode(self) -> ProviderAccessMode:
        """Resolve the active route without inferring identity from capabilities."""
        if (
            self.runtime_context is not None
            and self.runtime_context.access_mode in self.access_modes
        ):
            return self.runtime_context.access_mode
        if (
            self.default_access_policy_id is ProviderAccessPolicy.OPERATOR_PUBLIC
            and ProviderAccessMode.ANONYMOUS in self.access_modes
        ):
            return ProviderAccessMode.ANONYMOUS
        if self.default_access_policy_id is not None:
            default_mode = self.default_access_policy_id.access_mode
            if default_mode in self.access_modes:
                return default_mode
        for mode in (
            ProviderAccessMode.ANONYMOUS,
            ProviderAccessMode.OPERATOR_MANAGED,
        ):
            if mode in self.access_modes:
                return mode
        return ProviderAccessMode.ANONYMOUS


def provider_user_action(
    status: ProviderSupportStatus,
    provider_key: str | None = None,
    *,
    download_available: bool = False,
    access_mode: ProviderAccessMode = ProviderAccessMode.ANONYMOUS,
) -> str | None:
    """Return the single public recovery message for one Provider state."""
    sample = {
        ProviderAccessMode.ANONYMOUS: "公开样本",
        ProviderAccessMode.GUEST: "游客线路样本",
        ProviderAccessMode.OPERATOR_MANAGED: "受控线路样本",
    }[access_mode]
    if provider_key == ProviderKey.YOUKU:
        return YOUKU_DOWNLOAD_ACTION
    if provider_key == ProviderKey.QQVIDEO:
        return QQVIDEO_DOWNLOAD_ACTION
    if status is ProviderSupportStatus.ACCESS_REQUIRED and download_available:
        return "真实下载已完成验证；当前链接仍可能因平台授权或验证要求失败。"
    if provider_key == ProviderKey.WECHAT_CHANNELS:
        return (
            "仅支持分享页直接公开非加密媒体的单视频；"
            "平台未公开媒体时请上传自己拥有或已获授权的文件。"
        )
    if provider_key == ProviderKey.HONGGUO_WEB:
        return (
            "已接入红果官方分享链接当前单集；"
            "不支持 App 受保护媒体、全集抓取或批量下载。"
        )
    if (
        provider_key == ProviderKey.XIAOHONGSHU
        and status is ProviderSupportStatus.DEGRADED
    ):
        return (
            "当前出口受到小红书官方风控；失效笔记会单独提示，"
            "请使用新的公开分享链接后稍后重试。"
        )
    if status is ProviderSupportStatus.ACCESS_REQUIRED:
        if access_mode is ProviderAccessMode.OPERATOR_MANAGED:
            return (
                "当前线路需要平台授权或验证；服务端会复用部署机器已连接的 Chrome 会话，"
                "请确认 Chrome 扩展已连接，并在日常 Chrome 中处理该平台的登录或验证。"
            )
        return (
            "该平台当前要求额外授权或验证；请稍后重试，或上传你拥有或已获授权的文件。"
        )
    if status in {
        ProviderSupportStatus.DEGRADED,
        ProviderSupportStatus.RATE_LIMITED,
        ProviderSupportStatus.BLOCKED,
    }:
        return "平台当前不稳定，请稍后重试。"
    if status is ProviderSupportStatus.UNKNOWN:
        if download_available:
            return f"{sample}已完成真实下载验证；完整视频分析链路仍待验证。"
        return "该平台尚未完成当前版本的真实下载验证。"
    if status is ProviderSupportStatus.DISABLED:
        return "当前未开放此平台下载。"
    return None
