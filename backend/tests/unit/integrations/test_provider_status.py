from app.integrations.provider_status import configured_provider_statuses
from app.schemas.providers import ProviderStatusResponse
from app.services.provider_types import (
    ProviderCapability,
    ProviderIdentity,
    ProviderKey,
    ProviderSupportStatus,
)


def test_registry_capabilities_are_not_download_acceptance_evidence():
    statuses = configured_provider_statuses()
    assert statuses
    for item in statuses:
        public = ProviderStatusResponse.from_view(item).model_dump()
        assert item.identity in ProviderIdentity
        assert item.status in ProviderSupportStatus
        assert "download_available" not in public
        assert "evidence_state" not in public
        assert "access_modes" not in public
        assert "last_verified_at" not in public
    bilibili = next(item for item in statuses if item.key == "bilibili")
    assert bilibili.download_supported
    assert bilibili.identity is ProviderIdentity.PREFER


def test_dailymotion_unknown_status_exposes_anonymous_entry_not_verification():
    item = next(
        item
        for item in configured_provider_statuses()
        if item.key == ProviderKey.DAILYMOTION
    )
    public = ProviderStatusResponse.from_view(item)
    assert public.registered and public.extractor_exists and public.download_supported
    assert public.status is ProviderSupportStatus.UNKNOWN
    assert public.identity is ProviderIdentity.NONE
    assert public.capabilities == (ProviderCapability.SINGLE_VIDEO,)
    assert set(public.hosts) == {"dailymotion.com", "www.dailymotion.com", "dai.ly"}
    assert not public.host_suffixes
    assert public.user_action is None
    assert "last_verified_at" not in public.model_dump()


def test_required_identity_action_explains_login_requirement_for_extractors():
    required = [
        item
        for item in configured_provider_statuses()
        if item.identity is ProviderIdentity.REQUIRED and item.extractor_exists
    ]
    assert required
    for item in required:
        assert item.user_action is not None
        assert "需要登录" in item.user_action
        assert "无需登录" not in item.user_action


def test_wechat_channels_exposes_official_share_delivery_without_verified_support():
    channels = next(
        item
        for item in configured_provider_statuses()
        if item.key == ProviderKey.WECHAT_CHANNELS
    )
    public = ProviderStatusResponse.from_view(channels)
    assert public.registered
    assert public.extractor_exists
    assert public.download_supported
    assert public.status is ProviderSupportStatus.UNKNOWN
    assert public.identity is ProviderIdentity.REQUIRED
    assert set(public.capabilities) == {
        ProviderCapability.SINGLE_VIDEO,
        ProviderCapability.SHORT_VIDEO,
    }
    assert public.user_action is not None
    assert "需要登录元宝" in public.user_action
    assert "元宝页面打开" in public.user_action
    assert "官方分享链接" in public.user_action
    assert "非加密文件" in public.user_action
    assert all(word not in public.user_action for word in ("公开", "免费", "完整"))
    assert "last_verified_at" not in public.model_dump()


def test_official_account_articles_remain_discovery_only():
    article = next(
        item
        for item in configured_provider_statuses()
        if item.key == ProviderKey.WECHAT_OFFICIAL_ACCOUNT_ARTICLE
    )
    public = ProviderStatusResponse.from_view(article)
    assert public.registered
    assert not public.extractor_exists
    assert not public.download_supported
    assert not public.capabilities
    assert public.identity is ProviderIdentity.NONE
    assert public.user_action == "支持公开文章视频发现与显式选择。"
