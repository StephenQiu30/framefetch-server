from __future__ import annotations

import os

from app.core.config import Settings
from app.core.security.ai_provider_cipher import FernetAiProviderSecretCipher
from app.integrations.ai_cli.environment import minimum_host_environment
from app.integrations.ai_cli.errors import AnalysisCliError
from app.services.ai_providers import AiProviderRepository
from app.services.analysis_execution.ports import AnalyzerSelection
from app.workers.analysis.profile_runtime import build_profile_runtime


class ConfiguredAnalyzerResolver:
    """Resolve the active DB profile for every task and cache its CLI adapter."""

    def __init__(
        self,
        settings: Settings,
        repository: AiProviderRepository,
        cipher: FernetAiProviderSecretCipher,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._cipher = cipher
        self._cached_stamp: tuple[str, object] | None = None
        self._cached: AnalyzerSelection | None = None

    async def resolve(self) -> AnalyzerSelection:
        if not self._settings.analysis_enabled:
            raise AnalysisCliError("analysis_cli_unavailable")
        profile = await self._repository.get_active_profile()
        if profile is None:
            raise AnalysisCliError("analysis_cli_unavailable")
        stamp = (profile.key, profile.updated_at)
        if self._cached_stamp == stamp and self._cached is not None:
            return self._cached
        runtime = build_profile_runtime(
            self._settings,
            profile,
            self._cipher,
            environment=authentication_environment(),
        )
        selection = AnalyzerSelection(
            analyzer=runtime.analyzer,
            provider=profile.key,
            model=runtime.model,
            cli_version=runtime.cli_version,
        )
        self._cached_stamp = stamp
        self._cached = selection
        return selection


def authentication_environment() -> dict[str, str]:
    # Build from an explicit allowlist so inherited API credentials can never
    # reach the CLI. Windows still needs its core runtime variables for DNS
    # and process creation, so keep that non-secret allowlist in one place.
    return minimum_host_environment(os.environ.get("PATH", "/usr/bin:/bin"))
