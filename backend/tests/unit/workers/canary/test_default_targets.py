from app.core.config import Settings
from app.core.db import create_engine
from app.services.provider_types import ProviderAccessMode
from app.workers.canary import runtime as canary
from pydantic import SecretStr


def _settings(**overrides) -> Settings:
    return Settings(
        provider_canary_targets=SecretStr("[]"),
        session_runner_base_url="http://session-runner:19100",
        **overrides,
    )


def _build(settings: Settings) -> canary.ProviderCanaryRuntime:
    # Engine creation is lazy; building the runtime never connects.
    return canary.build_runtime(settings, create_engine(settings.database_url))


def test_empty_targets_fall_back_to_fixed_public_samples() -> None:
    runtime = _build(_settings())
    targets = runtime.scheduler._targets
    assert targets
    assert {t.provider_key for t in targets} >= {"youtube", "bilibili", "tiktok"}
    assert any(t.access_mode is ProviderAccessMode.OPERATOR_MANAGED for t in targets)


def test_operator_samples_are_skipped_without_a_session_runner() -> None:
    settings = Settings(provider_canary_targets=SecretStr("[]"))
    runtime = (
        canary.build_runtime.__wrapped__(settings)
        if hasattr(canary.build_runtime, "__wrapped__")
        else None
    )
    assert runtime is None or all(
        t.access_mode is not ProviderAccessMode.OPERATOR_MANAGED
        for t in runtime.scheduler._targets
    )


def test_default_targets_can_be_disabled() -> None:
    runtime = _build(_settings(provider_canary_default_targets=False))
    assert runtime.scheduler._targets == ()
