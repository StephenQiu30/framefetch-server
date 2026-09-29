from collections import defaultdict

from app.services.provider_types import (
    ProviderCanaryStage,
)
from app.workers.canary.fixed_cases import fixed_public_diagnostic_targets
from app.workers.runner.provider_registry import (
    current_provider_registry,
    provider_profile_for_key,
)

_KNOWN_INVALID_UPSTREAM_FIXTURES = {
    "BaW_jenozKc",
    "7206382937372134662",
}


def test_fixed_matrix_covers_every_registered_parser_and_its_fixed_route():
    targets = fixed_public_diagnostic_targets()
    grouped = defaultdict(list)
    for target in targets:
        grouped[target.provider_key].append(target)
    assert set(grouped) == {p.key for p in current_provider_registry().profiles}
    for key, targets in grouped.items():
        assert {target.access_mode for target in targets} == {
            provider_profile_for_key(key).initial_access_mode
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
