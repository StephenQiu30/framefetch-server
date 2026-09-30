"""Registry-derived capabilities, checked again at the execution boundary."""

import json
from dataclasses import asdict
from hashlib import sha256

from app.services.downloads.resolution import ResolutionCapability
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import (
    ProviderProfile,
    current_provider_registry,
)
from app.workers.runner.release_identity import runtime_code_sha256
from app.workers.runner.settings import RunnerSettings


def resolution_capability(
    profile: ProviderProfile, settings: RunnerSettings
) -> ResolutionCapability:
    strategies = profile.resolution_strategies
    document = {
        "provider_key": profile.key,
        "profile_version": profile.version,
        "access_policy": profile.access_policy,
        "capabilities": sorted(profile.capabilities),
        "strategies": [
            {
                **asdict(item),
                "allowed_failure_classes": sorted(item.allowed_failure_classes),
            }
            for item in strategies
        ],
        "engine_commit": settings.runner_ytdlp_commit,
        "runtime": {
            item.access_mode: runtime_code_sha256(
                profile.key, access_mode=item.access_mode
            )
            for item in strategies
        },
        "egress": settings.egress_affinity_for(profile.key),
    }
    revision = sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ResolutionCapability(
        profile.key,
        profile.version,
        profile.access_policy,
        tuple(sorted(profile.capabilities)),
        strategies,
        revision,
    )


def resolution_capabilities(
    settings: RunnerSettings,
) -> tuple[ResolutionCapability, ...]:
    registry = current_provider_registry()
    profiles = (*registry.profiles, registry.profile_for_key("generic"))
    return tuple(resolution_capability(profile, settings) for profile in profiles)


def require_resolution_strategy(
    profile: ProviderProfile,
    settings: RunnerSettings,
    strategy_id: str,
    plan_revision: str,
) -> None:
    capability = resolution_capability(profile, settings)
    if capability.revision != plan_revision:
        raise RunnerFailure("context_changed", status=409)
    if not any(
        item.enabled and item.strategy_id == strategy_id
        for item in capability.strategies
    ):
        raise RunnerFailure("provider_unsupported", status=422)
