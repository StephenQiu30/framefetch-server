from app.integrations.provider_status import configured_provider_statuses
from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_access import ProviderAccessPolicy as Policy
from app.services.provider_types import (
    ProviderAccessMode as Mode,
)
from app.workers.runner.provider_registry import current_provider_registry


def test_public_routes_do_not_require_a_chrome_session():
    for item in configured_provider_statuses():
        assert item.access_modes == (
            (Mode.ANONYMOUS,)
            if item.key
            in frozenset(
                p.key
                for p in current_provider_registry().profiles
                if p.initial_access_mode is Mode.ANONYMOUS
            )
            else ()
        )
        assert not item.download_available
        assert all(
            policy.id.access_mode
            is (
                Mode.ANONYMOUS
                if item.key
                in current_provider_registry().keys_for_policy(
                    ProviderAccessPolicy.PUBLIC
                )
                else Mode.OPERATOR_MANAGED
            )
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
        assert item.access_modes == (
            (Mode.OPERATOR_MANAGED,)
            if key in {"qqvideo", "youku"}
            else (Mode.ANONYMOUS, Mode.OPERATOR_MANAGED)
        )
        assert not item.download_available
        assert item.default_access_policy_id is (
            Policy.PERSONAL_ENTITLED
            if key in {"qqvideo", "youku"}
            else Policy.OPERATOR_PUBLIC
        )
    assert statuses["instagram"].access_modes == (Mode.ANONYMOUS,)
    assert all(
        item.access_policies[0].configured
        for item in statuses.values()
        if item.access_policies
    )
