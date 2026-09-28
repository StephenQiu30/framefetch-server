from collections import defaultdict

from app.services.provider_types import (
    ProviderAccessMode,
    ProviderCanaryStage,
    ProviderSupportStatus,
)
from app.services.site_sessions import known_session_provider_keys
from app.workers.canary.fixed_cases import fixed_public_diagnostic_targets
from app.workers.runner.provider_registry import current_provider_registry

_KNOWN_INVALID_UPSTREAM_FIXTURES = {
    "BaW_jenozKc",
    "7206382937372134662",
}

_FIXED_OPERATOR_PROVIDERS = {
    "reddit",
    "wechat_channels",
    "youtube",
}
_FIXED_GUEST_PROVIDERS = {"douyin"}
_PROVEN_ANONYMOUS_SESSION_PROVIDERS = {
    "facebook",
    "instagram",
    "pinterest",
    "x",
    "xiaohongshu",
}


def test_fixed_public_matrix_covers_every_registered_provider_and_stage() -> None:
    targets = fixed_public_diagnostic_targets()
    grouped: defaultdict[str, list] = defaultdict(list)
    for target in targets:
        grouped[target.provider_key].append(target)

    assert set(grouped) == {
        profile.key
        for profile in current_provider_registry().profiles
        if profile.support_status is not ProviderSupportStatus.DISABLED
        and ProviderAccessMode.ANONYMOUS in profile.access_modes
    }
    # Youku and Tencent Video have no public fixed matrix: account-only media.
    assert known_session_provider_keys() - {"youku", "qqvideo"} == (
        _FIXED_OPERATOR_PROVIDERS
        | _FIXED_GUEST_PROVIDERS
        | _PROVEN_ANONYMOUS_SESSION_PROVIDERS
    )
    for provider, provider_targets in grouped.items():
        expected_mode = (
            ProviderAccessMode.OPERATOR_MANAGED
            if provider in _FIXED_OPERATOR_PROVIDERS
            else ProviderAccessMode.GUEST
            if provider in _FIXED_GUEST_PROVIDERS
            else ProviderAccessMode.ANONYMOUS
        )
        assert {target.access_mode for target in provider_targets} == {expected_mode}
        assert {target.stage for target in provider_targets} == {
            ProviderCanaryStage.METADATA,
            ProviderCanaryStage.MEDIA,
        }
        assert len({target.target_id for target in provider_targets}) == 1
        assert len({target.safe_url() for target in provider_targets}) == 1


def test_session_capable_public_cases_use_their_proven_routes() -> None:
    targets = tuple(
        item
        for item in fixed_public_diagnostic_targets()
        if item.provider_key in _PROVEN_ANONYMOUS_SESSION_PROVIDERS
    )

    assert {item.access_mode for item in targets} == {ProviderAccessMode.ANONYMOUS}
    assert {item.provider_key for item in targets} == (
        _PROVEN_ANONYMOUS_SESSION_PROVIDERS
    )
    assert {item.stage for item in targets} == {
        ProviderCanaryStage.METADATA,
        ProviderCanaryStage.MEDIA,
    }


def test_fixed_public_matrix_does_not_reuse_known_invalid_upstream_fixtures() -> None:
    urls = tuple(target.safe_url() for target in fixed_public_diagnostic_targets())

    assert all(
        marker not in url for marker in _KNOWN_INVALID_UPSTREAM_FIXTURES for url in urls
    )
