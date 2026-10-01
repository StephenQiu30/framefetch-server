"""Registry capability snapshot without runtime admission or canary evidence."""

from app.services.provider_types import (
    ProviderIdentity,
    ProviderKey,
    ProviderSupportStatus,
)
from app.services.providers import ProviderStatusView
from app.workers.runner.provider_registry import current_provider_registry


def configured_provider_statuses() -> tuple[ProviderStatusView, ...]:
    configured = tuple(
        ProviderStatusView(
            key=profile.key,
            display_name=profile.display_name,
            registered=True,
            extractor_exists=True,
            capabilities=tuple(sorted(profile.capabilities, key=str)),
            identity=profile.identity,
            status=profile.support_status,
            user_action=(
                "身份层将在 R4 重建；当前仅执行匿名解析，受限内容可导入已有文件。"
                if profile.identity is ProviderIdentity.REQUIRED
                else None
            ),
            hosts=tuple(sorted(profile.hosts)),
            host_suffixes=tuple(sorted(profile.host_suffixes)),
        )
        for profile in current_provider_registry().profiles
    )
    return configured + (
        ProviderStatusView(
            key=ProviderKey.WECHAT_OFFICIAL_ACCOUNT_ARTICLE,
            display_name="微信公众号文章",
            registered=True,
            extractor_exists=False,
            capabilities=(),
            identity=ProviderIdentity.NONE,
            status=ProviderSupportStatus.UNKNOWN,
            user_action="支持公开文章视频发现与显式选择。",
        ),
    )
