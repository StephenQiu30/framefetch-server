"""Run the fixed public diagnostics without printing source URLs."""

from __future__ import annotations

import argparse
import asyncio
import json

from app.core.config import get_settings_for_role
from app.core.db import create_engine
from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_types import ProviderCanaryOutcome, ProviderCanaryStage
from app.workers.canary.fixed_cases import fixed_public_diagnostic_targets
from app.workers.canary.runtime import build_runtime
from app.workers.canary.targets import ProviderCanaryTarget
from app.workers.runner.provider_registry import current_provider_registry


async def _run(providers: frozenset[str], stage: str) -> int:
    cases = fixed_public_diagnostic_targets()
    if providers - {target.provider_key for target in cases}:
        print(
            json.dumps(
                {
                    "matrix_complete": False,
                    "target_count": 0,
                    "error": "unknown_provider",
                }
            )
        )
        return 2
    targets = tuple(
        target
        for target in cases
        if (not providers or target.provider_key in providers)
        and (stage == "all" or target.stage.value == stage)
    )
    settings = get_settings_for_role("worker")
    engine = create_engine(settings.database_url)
    runtime = build_runtime(settings, engine)
    results: list[dict[str, object]] = []
    try:
        slots = asyncio.Semaphore(3)

        async def execute(target: ProviderCanaryTarget) -> dict[str, object]:
            async with slots:
                result = await runtime.service.execute(target)
            return {
                "provider_key": result.provider_key,
                "profile_version": result.profile_version,
                "stage": result.stage.value,
                "access_mode": result.access_mode.value,
                "outcome": result.outcome.value,
                "stable_error_code": result.stable_error_code,
                "duration_ms": result.duration_ms,
            }

        results = list(await asyncio.gather(*(execute(target) for target in targets)))
    finally:
        try:
            await runtime.close()
        finally:
            await engine.dispose()
    passed = all(
        item["outcome"] == ProviderCanaryOutcome.SUCCEEDED.value for item in results
    )
    print(
        json.dumps(
            {
                "matrix_complete": passed and bool(results),
                "target_count": len(results),
                "results": results,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0 if passed and results else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run fixed public Provider metadata/media diagnostics.",
    )
    parser.add_argument("--provider", action="append", default=[])
    parser.add_argument("--native-public", action="store_true")
    parser.add_argument(
        "--stage",
        choices=(
            "all",
            ProviderCanaryStage.METADATA.value,
            ProviderCanaryStage.MEDIA.value,
        ),
        default="all",
    )
    arguments = parser.parse_args()
    providers = frozenset(arguments.provider)
    if arguments.native_public:
        public_providers = current_provider_registry().keys_for_policy(
            ProviderAccessPolicy.PUBLIC
        )
        if providers and not providers <= public_providers:
            parser.error("--native-public only accepts native public providers")
        providers = providers or public_providers
    raise SystemExit(asyncio.run(_run(providers, arguments.stage)))


if __name__ == "__main__":
    main()
