"""Configured Provider status snapshot without credentials or canary targets."""

from __future__ import annotations

from collections.abc import Set

from app.services.provider_access import (
    NATIVE_PUBLIC_PROVIDERS,
    ProviderAccessPolicy,
    provider_access_policies,
)
from app.services.provider_types import (
    ProviderAccessMode,
    ProviderKey,
    ProviderSupportStatus,
)
from app.services.providers import (
    ProviderAccessPolicyView,
    ProviderStatusView,
    provider_user_action,
)
from app.workers.runner.provider_registry import (
    ProviderProfile,
    current_provider_registry,
)


def configured_provider_statuses(
    enabled_operator_keys: Set[str] = frozenset(),
) -> tuple[ProviderStatusView, ...]:
    configured = tuple(
        _configured_status(profile, enabled_operator_keys)
        for profile in current_provider_registry().profiles
    )
    non_runner = (
        ProviderStatusView(
            key=ProviderKey.WECHAT_OFFICIAL_ACCOUNT_ARTICLE,
            display_name="微信公众号文章",
            profile_version=None,
            registered=True,
            extractor_exists=False,
            capabilities=(),
            access_modes=(),
            status=ProviderSupportStatus.UNKNOWN,
            last_checked_at=None,
            last_check_succeeded=None,
            download_available=False,
            last_media_verified_at=None,
            last_verified_at=None,
            user_action="支持公开文章视频发现与显式选择；原生视频下载尚未通过发布验收。",
        ),
    )
    return configured + non_runner


current_provider_statuses = configured_provider_statuses


def _configured_status(
    profile: ProviderProfile,
    enabled_operator_keys: Set[str],
) -> ProviderStatusView:
    access_modes = (
        ()
        if profile.support_status is ProviderSupportStatus.DISABLED
        else _effective_access_modes(
            profile.key, profile.access_modes, enabled_operator_keys
        )
    )
    status = (
        profile.support_status
        if access_modes or profile.support_status is ProviderSupportStatus.DISABLED
        else ProviderSupportStatus.ACCESS_REQUIRED
    )
    policies = (
        ()
        if profile.support_status is ProviderSupportStatus.DISABLED
        else tuple(
            ProviderAccessPolicyView(
                id=policy, configured=policy.access_mode in access_modes
            )
            for policy in provider_access_policies(
                profile.key,
                (ProviderAccessMode.ANONYMOUS,)
                if profile.key in NATIVE_PUBLIC_PROVIDERS
                else (ProviderAccessMode.OPERATOR_MANAGED,),
            )
        )
    )
    default_policy = (
        (
            ProviderAccessPolicy.PUBLIC
            if profile.key in NATIVE_PUBLIC_PROVIDERS
            else ProviderAccessPolicy.PERSONAL_ENTITLED
            if profile.key in {"qqvideo", "youku"}
            else ProviderAccessPolicy.OPERATOR_PUBLIC
        )
        if policies
        else None
    )
    if default_policy is not None and default_policy not in {
        item.id for item in policies
    }:
        raise ValueError("default provider access policy is not admitted")
    missing_default = any(
        item.id is default_policy and not item.configured for item in policies
    )
    if default_policy is ProviderAccessPolicy.PUBLIC_SESSION and not missing_default:
        # Configured visitor preparation is not an account requirement or a
        # successful download. Current, matching canary evidence decides that.
        status = ProviderSupportStatus.UNKNOWN
    return ProviderStatusView(
        key=profile.key,
        display_name=profile.display_name,
        profile_version=profile.version,
        registered=True,
        extractor_exists=True,
        capabilities=tuple(sorted(profile.capabilities, key=str)),
        access_modes=access_modes,
        status=status,
        last_checked_at=None,
        last_check_succeeded=None,
        download_available=False,
        last_media_verified_at=None,
        last_verified_at=None,
        user_action=(
            "平台会话尚未配置；请部署者导入登录状态。"
            + (provider_user_action(status, profile.key) or "")
            if missing_default
            else provider_user_action(status, profile.key)
        ),
        access_policies=policies,
        default_access_policy_id=default_policy,
        hosts=tuple(sorted(profile.hosts)),
        host_suffixes=tuple(sorted(profile.host_suffixes)),
    )


def _effective_access_modes(
    provider_key: str,
    declared: tuple[ProviderAccessMode, ...],
    enabled_operator_keys: Set[str],
) -> tuple[ProviderAccessMode, ...]:
    if provider_key in NATIVE_PUBLIC_PROVIDERS:
        return (ProviderAccessMode.ANONYMOUS,)
    return (
        (ProviderAccessMode.OPERATOR_MANAGED,)
        if provider_key in enabled_operator_keys
        else ()
    )
