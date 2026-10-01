"""Registry capability snapshot; file delivery is verified separately."""

from app.services.provider_types import (
    ProviderIdentity,
    ProviderKey,
)
from app.services.providers import ProviderStatusView
from app.workers.runner.provider_registry import current_provider_registry


def configured_provider_statuses() -> tuple[ProviderStatusView, ...]:
    configured = tuple(
        ProviderStatusView(
            key=profile.key,
            display_name=profile.display_name,
            registered=True,
            extractor_exists=profile.key != ProviderKey.WECHAT_OFFICIAL_ACCOUNT_ARTICLE,
            capabilities=()
            if profile.key == ProviderKey.WECHAT_OFFICIAL_ACCOUNT_ARTICLE
            else tuple(sorted(profile.capabilities, key=str)),
            identity=profile.identity,
            status=profile.support_status,
            user_action=(
                "支持公开文章视频发现与显式选择。"
                if profile.key == ProviderKey.WECHAT_OFFICIAL_ACCOUNT_ARTICLE
                else "此平台需要登录身份；无法解析时，可导入已有文件。"
                if profile.identity is ProviderIdentity.REQUIRED
                else None
            ),
            hosts=tuple(sorted(profile.hosts)),
            host_suffixes=tuple(sorted(profile.host_suffixes)),
        )
        for profile in current_provider_registry().profiles
    )
    return configured
