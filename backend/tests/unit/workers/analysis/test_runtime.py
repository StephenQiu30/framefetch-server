from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.core.config import Settings
from app.integrations.ai_api.analyzer import ApiAnalyzer
from app.integrations.ai_cli.codex import CodexAppServerVideoAnalyzer
from app.integrations.ai_cli.preflight import CliCapabilities
from app.services.ai_providers import (
    AiProviderAuthMode,
    AiProviderEngine,
    AiProviderProfile,
)
from app.workers.analysis import profile_runtime
from app.workers.analysis.providers import (
    ConfiguredAnalyzerResolver,
    authentication_environment,
)


def test_worker_discards_api_key_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "must-not-be-used")

    environment = authentication_environment()

    assert "OPENAI_API_KEY" not in environment
    assert "ANTHROPIC_AUTH_TOKEN" not in environment
    assert "HOME" in environment
    if sys.platform == "win32":
        assert environment["SYSTEMROOT"] == os.environ["SYSTEMROOT"]
        if "WINDIR" in os.environ:
            assert environment["WINDIR"] == os.environ["WINDIR"]


@pytest.mark.asyncio
async def test_local_codex_runtime_is_selected_from_the_database_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    calls: list[tuple[str, bool]] = []

    def successful_preflight(
        provider: str, *args: object, **kwargs: object
    ) -> CliCapabilities:
        del args
        calls.append((provider, bool(kwargs["verify_authentication"])))
        return CliCapabilities(
            provider=provider,
            binary=Path(sys.executable),
            version="controlled",
            ffmpeg=Path(sys.executable),
            ffprobe=Path(sys.executable),
        )

    class Repository:
        async def get_active_profile(self) -> AiProviderProfile:
            return AiProviderProfile(
                key="local-codex",
                display_name="本机 Codex",
                engine=AiProviderEngine.CODEX,
                auth_mode=AiProviderAuthMode.HOST_LOGIN,
                base_url=None,
                model="gpt-database-model",
                credential_ciphertext=None,
                credential_key_id=None,
                is_active=True,
                created_at=now,
                updated_at=now,
            )

    monkeypatch.setattr(profile_runtime, "preflight", successful_preflight)
    resolver = ConfiguredAnalyzerResolver(
        Settings(app_env="test", analysis_enabled=True, _env_file=None),
        Repository(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
    )

    selection = await resolver.resolve()

    assert isinstance(selection.analyzer, CodexAppServerVideoAnalyzer)
    assert (selection.provider, selection.model) == (
        "local-codex",
        "gpt-database-model",
    )
    assert calls == [("codex", True)]


@pytest.mark.asyncio
async def test_active_api_provider_is_injected_only_into_selected_cli_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    def successful_preflight(*args: object, **kwargs: object) -> CliCapabilities:
        del args
        calls.append(bool(kwargs["verify_authentication"]))
        return CliCapabilities(
            provider="codex",
            binary=Path(sys.executable),
            version="controlled",
            ffmpeg=Path(sys.executable),
            ffprobe=Path(sys.executable),
        )

    class Repository:
        async def get_active_profile(self) -> AiProviderProfile:
            return AiProviderProfile(
                key="custom",
                display_name="Custom Provider",
                engine=AiProviderEngine.CODEX,
                auth_mode=AiProviderAuthMode.API_KEY,
                base_url="https://api.example.com/v1",
                model="gpt-custom",
                credential_ciphertext=b"ciphertext",
                credential_key_id="fernet-test",
                is_active=True,
                created_at=datetime(2026, 8, 13, tzinfo=UTC),
                updated_at=datetime(2026, 8, 13, tzinfo=UTC),
            )

    class Cipher:
        def decrypt(self, provider_key: str, ciphertext: bytes, key_id: str) -> str:
            assert (provider_key, ciphertext, key_id) == (
                "custom",
                b"ciphertext",
                "fernet-test",
            )
            return "secret-value"

    monkeypatch.setattr(profile_runtime, "preflight", successful_preflight)
    resolver = ConfiguredAnalyzerResolver(
        Settings(app_env="test", analysis_enabled=True, _env_file=None),
        Repository(),  # type: ignore[arg-type]
        Cipher(),  # type: ignore[arg-type]
    )

    selection = await resolver.resolve()
    again = await resolver.resolve()

    assert selection is again
    assert selection.provider == "custom"
    config = selection.analyzer._config  # type: ignore[attr-defined]
    assert dict(config.extra_environment) == {
        "VIDEO_ANALYSIS_PROVIDER_KEY": "secret-value"
    }
    assert any("api.example.com" in value for value in config.provider_arguments)
    assert all("secret-value" not in value for value in config.provider_arguments)
    assert calls == [False]


@pytest.mark.asyncio
async def test_updated_active_profile_rebuilds_adapter_for_next_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    updated_at = datetime(2026, 8, 13, tzinfo=UTC)

    def successful_preflight(*args: object, **kwargs: object) -> CliCapabilities:
        del args, kwargs
        calls.append("preflight")
        return CliCapabilities(
            provider="codex",
            binary=Path(sys.executable),
            version="controlled",
            ffmpeg=Path(sys.executable),
            ffprobe=Path(sys.executable),
        )

    class Repository:
        model = "model-a"
        secret = b"cipher-a"
        changed_at = updated_at

        async def get_active_profile(self) -> AiProviderProfile:
            return AiProviderProfile(
                key="custom",
                display_name="Custom Provider",
                engine=AiProviderEngine.CODEX,
                auth_mode=AiProviderAuthMode.API_KEY,
                base_url="https://api.example.com/v1",
                model=self.model,
                credential_ciphertext=self.secret,
                credential_key_id="fernet-test",
                is_active=True,
                created_at=updated_at,
                updated_at=self.changed_at,
            )

    class Cipher:
        def decrypt(self, provider_key: str, ciphertext: bytes, key_id: str) -> str:
            assert provider_key == "custom" and key_id == "fernet-test"
            return ciphertext.decode()

    repository = Repository()
    monkeypatch.setattr(profile_runtime, "preflight", successful_preflight)
    resolver = ConfiguredAnalyzerResolver(
        Settings(app_env="test", analysis_enabled=True, _env_file=None),
        repository,  # type: ignore[arg-type]
        Cipher(),  # type: ignore[arg-type]
    )

    first = await resolver.resolve()
    repository.model = "model-b"
    repository.secret = b"cipher-b"
    repository.changed_at = datetime(2026, 8, 14, tzinfo=UTC)
    second = await resolver.resolve()

    assert second is not first
    assert (first.model, second.model) == ("model-a", "model-b")
    assert dict(second.analyzer._config.extra_environment) == {  # type: ignore[attr-defined]
        "VIDEO_ANALYSIS_PROVIDER_KEY": "cipher-b"
    }
    assert calls == ["preflight", "preflight"]


@pytest.mark.asyncio
async def test_deepseek_profile_uses_web_secret_and_media_tools_without_cli_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)

    class Repository:
        async def get_active_profile(self) -> AiProviderProfile:
            return AiProviderProfile(
                key="deepseek-main",
                display_name="DeepSeek 主线路",
                engine=AiProviderEngine.DEEPSEEK,
                auth_mode=AiProviderAuthMode.API_KEY,
                base_url="https://api.deepseek.com",
                model="deepseek-v4-flash-vision-exp",
                credential_ciphertext=b"ciphertext",
                credential_key_id="fernet-test",
                is_active=True,
                created_at=now,
                updated_at=now,
            )

    class Cipher:
        def decrypt(self, provider_key: str, ciphertext: bytes, key_id: str) -> str:
            assert (provider_key, ciphertext, key_id) == (
                "deepseek-main",
                b"ciphertext",
                "fernet-test",
            )
            return "web-managed-secret"

    media_calls: list[dict[str, object]] = []

    def media_preflight(**kwargs: object) -> tuple[Path, Path]:
        media_calls.append(kwargs)
        return Path(sys.executable), Path(sys.executable)

    monkeypatch.setattr(profile_runtime, "media_preflight", media_preflight)
    monkeypatch.setattr(
        profile_runtime,
        "preflight",
        lambda *args, **kwargs: pytest.fail(
            f"DeepSeek must not preflight a host CLI: {args!r} {kwargs!r}"
        ),
    )
    resolver = ConfiguredAnalyzerResolver(
        Settings(app_env="test", analysis_enabled=True, _env_file=None),
        Repository(),  # type: ignore[arg-type]
        Cipher(),  # type: ignore[arg-type]
    )

    selection = await resolver.resolve()

    assert isinstance(selection.analyzer, ApiAnalyzer)
    assert selection.provider == "deepseek-main"
    assert selection.model == "deepseek-v4-flash-vision-exp"
    assert selection.cli_version.startswith("langchain-deepseek/")
    assert len(media_calls) == 1
    assert "web-managed-secret" not in repr(selection.analyzer._model)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "engine", [AiProviderEngine.OPENAI, AiProviderEngine.OPENROUTER]
)
def test_direct_api_runtime_never_requires_a_cli(
    engine: AiProviderEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 9, 17, tzinfo=UTC)
    profile = AiProviderProfile(
        key="api",
        display_name="API",
        engine=engine,
        auth_mode=AiProviderAuthMode.API_KEY,
        base_url="https://openrouter.ai/api/v1",
        model="vendor/model",
        credential_ciphertext=b"encrypted",
        credential_key_id="test",
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    class Cipher:
        def decrypt(self, *args: object) -> str:
            return "controlled-secret"

    monkeypatch.setattr(
        profile_runtime, "preflight", lambda *a, **k: pytest.fail("CLI must not run")
    )
    monkeypatch.setattr(
        profile_runtime,
        "media_preflight",
        lambda **k: (Path(sys.executable), Path(sys.executable)),
    )
    runtime = profile_runtime.build_profile_runtime(
        Settings(app_env="test", _env_file=None), profile, Cipher(), environment={}
    )  # type: ignore[arg-type]
    assert isinstance(runtime.analyzer, ApiAnalyzer)
    assert runtime.model == "vendor/model"
    assert "chat-completions" in runtime.cli_version


def test_runtime_registry_covers_every_declared_engine() -> None:
    assert set(profile_runtime._RUNTIME_FACTORIES) == set(AiProviderEngine)
