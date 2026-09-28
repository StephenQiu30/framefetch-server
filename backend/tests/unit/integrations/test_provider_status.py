from app.integrations.provider_status import configured_provider_statuses
from app.services.provider_access import ProviderAccessPolicy as Policy
from app.services.provider_types import (
    ProviderAccessMode as Mode,
)
from app.services.provider_types import (
    ProviderSupportStatus as Status,
)


def test_unconfigured_platforms_never_advertise_anonymous_access():
    for item in configured_provider_statuses():
        assert item.access_modes == ()
        assert not item.download_available
        assert all(
            policy.id.access_mode is Mode.OPERATOR_MANAGED
            for policy in item.access_policies
        )


def test_configured_sessions_remain_unverified_until_real_media_evidence():
    statuses = {
        item.key: item
        for item in configured_provider_statuses(
            frozenset({"youtube", "douyin", "qqvideo", "youku"})
        )
    }
    for key in ("youtube", "douyin", "qqvideo", "youku"):
        item = statuses[key]
        assert item.access_modes == (Mode.OPERATOR_MANAGED,)
        assert not item.download_available
        assert item.default_access_policy_id is (
            Policy.PERSONAL_ENTITLED
            if key in {"qqvideo", "youku"}
            else Policy.OPERATOR_PUBLIC
        )
    assert statuses["instagram"].access_modes == ()
    assert statuses["instagram"].status is Status.ACCESS_REQUIRED
