from __future__ import annotations

import hashlib
import json
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
            binding_sha256=hashlib.sha256(
                json.dumps(
                    {
                        "profile": [
                            profile.key,
                            profile.display_name,
                            profile.engine.value,
                            profile.auth_mode.value,
                            profile.base_url,
                            profile.model,
                            profile.updated_at.isoformat(),
                            hashlib.sha256(
                                str(profile.credential_ciphertext).encode()
                            ).hexdigest(),
                        ],
                        "policy": [
                            str(self._settings.analysis_codex_binary),
                            str(self._settings.analysis_claude_binary),
                            str(self._settings.analysis_ffmpeg_binary),
                            str(self._settings.analysis_ffprobe_binary),
                            self._settings.analysis_timeout_seconds,
                            self._settings.analysis_max_stdout_bytes,
                            self._settings.analysis_max_stderr_bytes,
                            self._settings.analysis_max_workspace_bytes,
                            self._settings.analysis_max_workspace_files,
                            self._settings.analysis_max_frames,
                            self._settings.analysis_max_image_bytes,
                            self._settings.analysis_workspace_poll_seconds,
                            self._settings.analysis_terminate_grace_seconds,
                            self._settings.analysis_claude_max_turns,
                        ],
                        "runtime": [runtime.model, runtime.cli_version],
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
        )
        self._cached_stamp = stamp
        self._cached = selection
        return selection


def authentication_environment() -> dict[str, str]:
    # Build from an explicit allowlist so inherited API credentials can never
    # reach the CLI. Windows still needs its core runtime variables for DNS
    # and process creation, so keep that non-secret allowlist in one place.
    return minimum_host_environment(os.environ.get("PATH", "/usr/bin:/bin"))
