from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from importlib.metadata import version
from pathlib import Path

from app.core.config import Settings
from app.core.security.ai_provider_cipher import FernetAiProviderSecretCipher
from app.integrations.ai_api.analyzer import ApiAnalyzer
from app.integrations.ai_api.catalog import OpenRouterModelCatalog
from app.integrations.ai_api.chat import ChatCompletionsModel
from app.integrations.ai_api.client import build_model
from app.integrations.ai_api.config import ApiAdapterConfig
from app.integrations.ai_cli.claude import ClaudeCliVideoAnalyzer
from app.integrations.ai_cli.codex import CodexAppServerVideoAnalyzer
from app.integrations.ai_cli.config import CliAdapterConfig
from app.integrations.ai_cli.errors import AnalysisCliError
from app.integrations.ai_cli.preflight import media_preflight, preflight
from app.services.ai_providers import (
    AiProviderAuthMode,
    AiProviderEngine,
    AiProviderProfile,
)
from app.services.analysis_execution.ports import VideoAnalyzer


@dataclass(frozen=True, slots=True)
class AnalyzerRuntime:
    analyzer: VideoAnalyzer
    provider: str
    model: str
    cli_version: str


def build_profile_runtime(
    settings: Settings,
    profile: AiProviderProfile,
    cipher: FernetAiProviderSecretCipher,
    *,
    environment: Mapping[str, str],
) -> AnalyzerRuntime:
    factory = _RUNTIME_FACTORIES.get(profile.engine)
    if factory is None:
        raise AnalysisCliError("analysis_cli_unsupported")
    return factory(settings, profile, cipher, environment)


def _cli_runtime(
    settings: Settings,
    profile: AiProviderProfile,
    cipher: FernetAiProviderSecretCipher,
    environment: Mapping[str, str],
) -> AnalyzerRuntime:
    binary = (
        settings.analysis_codex_binary
        if profile.engine is AiProviderEngine.CODEX
        else settings.analysis_claude_binary
    )
    extra_environment: tuple[tuple[str, str], ...] = ()
    provider_arguments: tuple[str, ...] = ()
    if profile.auth_mode is AiProviderAuthMode.API_KEY:
        secret = _profile_secret(profile, cipher)
        if profile.engine is AiProviderEngine.CODEX:
            extra_environment = (("VIDEO_ANALYSIS_PROVIDER_KEY", secret),)
            provider_arguments = _codex_provider_arguments(profile)
        else:
            assert profile.base_url is not None
            extra_environment = (
                ("ANTHROPIC_API_KEY", secret),
                ("ANTHROPIC_BASE_URL", profile.base_url),
            )
    capabilities = preflight(
        profile.engine.value,
        cli_binary=binary,
        ffmpeg_binary=settings.analysis_ffmpeg_binary,
        ffprobe_binary=settings.analysis_ffprobe_binary,
        environment=environment,
        verify_authentication=profile.auth_mode is AiProviderAuthMode.HOST_LOGIN,
    )
    config = replace(
        _cli_config(
            settings,
            capabilities.binary,
            profile.model,
            capabilities.ffmpeg,
            capabilities.ffprobe,
        ),
        extra_environment=extra_environment,
        provider_arguments=provider_arguments,
    )
    analyzer: VideoAnalyzer = (
        CodexAppServerVideoAnalyzer(config)
        if profile.engine is AiProviderEngine.CODEX
        else ClaudeCliVideoAnalyzer(config)
    )
    return AnalyzerRuntime(analyzer, profile.key, profile.model, capabilities.version)


def _api_runtime(
    settings: Settings,
    profile: AiProviderProfile,
    cipher: FernetAiProviderSecretCipher,
    environment: Mapping[str, str],
) -> AnalyzerRuntime:
    if profile.base_url is None:
        raise AnalysisCliError("analysis_cli_not_authenticated")
    ffmpeg, ffprobe = media_preflight(
        ffmpeg_binary=settings.analysis_ffmpeg_binary,
        ffprobe_binary=settings.analysis_ffprobe_binary,
        environment=environment,
    )
    config = ApiAdapterConfig(
        model=profile.model,
        base_url=profile.base_url,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        timeout_seconds=settings.analysis_timeout_seconds,
        max_stdout_bytes=settings.analysis_max_stdout_bytes,
        max_stderr_bytes=settings.analysis_max_stderr_bytes,
        max_workspace_bytes=settings.analysis_max_workspace_bytes,
        max_workspace_files=settings.analysis_max_workspace_files,
        max_frames=settings.analysis_max_frames,
        max_image_bytes=settings.analysis_max_image_bytes,
        workspace_poll_seconds=settings.analysis_workspace_poll_seconds,
        terminate_grace_seconds=settings.analysis_terminate_grace_seconds,
    )
    secret = _profile_secret(profile, cipher)
    if profile.engine is AiProviderEngine.DEEPSEEK:
        model = build_model(config, secret)
        label = f"langchain-deepseek/{version('langchain-deepseek')}"
    else:
        model = ChatCompletionsModel(
            base_url=config.base_url,
            model=config.model,
            api_key=secret,
            timeout_seconds=config.timeout_seconds,
            maximum_bytes=config.max_stdout_bytes,
            catalog=OpenRouterModelCatalog()
            if profile.engine is AiProviderEngine.OPENROUTER
            else None,
        )
        label = f"chat-completions/httpx-{version('httpx')}"
    analyzer = ApiAnalyzer(config, model=model)
    return AnalyzerRuntime(analyzer, profile.key, profile.model, label)


def _profile_secret(
    profile: AiProviderProfile, cipher: FernetAiProviderSecretCipher
) -> str:
    if (
        profile.credential_ciphertext is None
        or profile.credential_key_id is None
        or profile.base_url is None
    ):
        raise AnalysisCliError("analysis_cli_not_authenticated")
    return cipher.decrypt(
        profile.key, profile.credential_ciphertext, profile.credential_key_id
    )


def _codex_provider_arguments(profile: AiProviderProfile) -> tuple[str, ...]:
    assert profile.base_url is not None
    values: tuple[tuple[str, object], ...] = (
        ("model_provider", "video_analysis"),
        ("model_providers.video_analysis.name", profile.display_name),
        ("model_providers.video_analysis.base_url", profile.base_url),
        ("model_providers.video_analysis.env_key", "VIDEO_ANALYSIS_PROVIDER_KEY"),
        ("model_providers.video_analysis.wire_api", "responses"),
    )
    return tuple(
        item for key, value in values for item in ("-c", f"{key}={json.dumps(value)}")
    )


def _cli_config(
    settings: Settings,
    binary: Path,
    model: str,
    ffmpeg: Path,
    ffprobe: Path,
) -> CliAdapterConfig:
    return CliAdapterConfig(
        binary=binary,
        model=model,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        timeout_seconds=settings.analysis_timeout_seconds,
        max_stdout_bytes=settings.analysis_max_stdout_bytes,
        max_stderr_bytes=settings.analysis_max_stderr_bytes,
        max_workspace_bytes=settings.analysis_max_workspace_bytes,
        max_workspace_files=settings.analysis_max_workspace_files,
        max_frames=settings.analysis_max_frames,
        max_image_bytes=settings.analysis_max_image_bytes,
        workspace_poll_seconds=settings.analysis_workspace_poll_seconds,
        terminate_grace_seconds=settings.analysis_terminate_grace_seconds,
        max_turns=settings.analysis_claude_max_turns,
    )


# Explicit strategy registry: unsupported engines must never fall through to Claude.
_RUNTIME_FACTORIES: Mapping[
    AiProviderEngine,
    Callable[
        [Settings, AiProviderProfile, FernetAiProviderSecretCipher, Mapping[str, str]],
        AnalyzerRuntime,
    ],
] = {
    AiProviderEngine.CODEX: _cli_runtime,
    AiProviderEngine.CLAUDE: _cli_runtime,
    AiProviderEngine.DEEPSEEK: _api_runtime,
    AiProviderEngine.OPENROUTER: _api_runtime,
    AiProviderEngine.OPENAI: _api_runtime,
}
