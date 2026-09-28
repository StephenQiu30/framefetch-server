from collections import defaultdict

from app.services.provider_types import (
    ProviderAccessMode,
    ProviderCanaryStage,
)
from app.services.site_sessions import known_session_provider_keys
from app.workers.canary.fixed_cases import fixed_public_diagnostic_targets

_KNOWN_INVALID_UPSTREAM_FIXTURES = {
    "BaW_jenozKc",
    "7206382937372134662",
}


def test_fixed_matrix_covers_supported_session_sites_without_anonymous_routes():
    targets = fixed_public_diagnostic_targets()
    grouped = defaultdict(list)
    for target in targets:
        grouped[target.provider_key].append(target)
    assert set(grouped) == known_session_provider_keys() - {"youku", "qqvideo"}
    for targets in grouped.values():
        assert {target.access_mode for target in targets} == {
            ProviderAccessMode.OPERATOR_MANAGED
        }
        assert {target.stage for target in targets} == {
            ProviderCanaryStage.METADATA,
            ProviderCanaryStage.MEDIA,
        }
        assert len({target.target_id for target in targets}) == 1


def test_fixed_public_matrix_does_not_reuse_known_invalid_upstream_fixtures() -> None:
    urls = tuple(target.safe_url() for target in fixed_public_diagnostic_targets())

    assert all(
        marker not in url for marker in _KNOWN_INVALID_UPSTREAM_FIXTURES for url in urls
    )
