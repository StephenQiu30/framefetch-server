from app.integrations.provider_status import configured_provider_statuses
from app.schemas.providers import ProviderStatusResponse
from app.services.provider_types import ProviderIdentity, ProviderSupportStatus


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


def test_required_identity_action_explains_login_requirement():
    required = [
        item
        for item in configured_provider_statuses()
        if item.identity is ProviderIdentity.REQUIRED
    ]
    assert required
    for item in required:
        assert item.user_action is not None
        assert "需要登录" in item.user_action
        assert "无需登录" not in item.user_action
