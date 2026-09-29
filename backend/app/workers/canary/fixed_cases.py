"""Fixed diagnostics; production canary URLs remain Secret-configured."""

from __future__ import annotations

from pathlib import Path

from app.workers.canary.targets import ProviderCanaryTarget, parse_canary_targets
from app.workers.runner.provider_registry import provider_profile_for_key
from pydantic import SecretStr

_CASES = Path(__file__).with_name("fixed_public_cases.json")


def fixed_public_diagnostic_targets() -> tuple[ProviderCanaryTarget, ...]:
    targets = parse_canary_targets(SecretStr(_CASES.read_text(encoding="utf-8")))
    return tuple(
        target.model_copy(
            update={
                "access_mode": provider_profile_for_key(
                    target.provider_key
                ).initial_access_mode
            }
        )
        for target in targets
    )
