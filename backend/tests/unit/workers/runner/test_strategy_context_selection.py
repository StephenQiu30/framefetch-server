"""A selected same-mode route must survive preparation and download validation."""

from dataclasses import replace
from pathlib import Path

import pytest
from app.services.provider_failures import FailurePhase
from app.services.provider_types import (
    MediaHandoff,
    ProviderAccessMode,
    ProviderSessionSource,
    ResolutionExecutionKind,
    ResolutionStrategy,
)
from app.workers.runner import service as service_module
from app.workers.runner.browser_runtime import browser_revision
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import ProviderRequest, provider_profile
from app.workers.runner.provider_sessions import ProviderSessionStore
from app.workers.runner.resolution_catalog import resolution_capability
from app.workers.runner.service import MediaRunnerService
from app.workers.runner.settings import RunnerSettings

URL = "https://media.example/video"
BROWSER = ResolutionStrategy(
    "browser-html5",
    "html5-page",
    "html5-v1",
    ResolutionExecutionKind.BROWSER,
    ProviderAccessMode.ANONYMOUS,
    ProviderSessionSource.NONE,
    ("browser_runtime",),
    frozenset(),
    MediaHandoff.HTTP_TRANSFERABLE,
    "semantic-media-and-artifact",
)


def _profile(browser=BROWSER):
    primary = provider_profile(URL)
    return replace(
        primary, resolution_strategies=(*primary.resolution_strategies, browser)
    )


def _settings(tmp_path: Path, **overrides) -> RunnerSettings:
    return RunnerSettings(
        runner_hmac_secret="s" * 32,
        runner_egress_proxy="http://egress-proxy:3128",
        runner_workspace_root=tmp_path,
        runner_browser_enabled=True,
        **overrides,
    )


async def test_same_mode_browser_context_is_frozen_and_not_changed_to_http(tmp_path):
    profile, settings = _profile(), _settings(tmp_path)
    store = ProviderSessionStore(settings)
    primary = await store.context_for(profile)
    selected = await store.context_for(profile, strategy_id=BROWSER.strategy_id)

    assert selected.strategy_id == BROWSER.strategy_id
    assert selected.adapter_revision == BROWSER.adapter_revision
    assert selected.client_profile_id == "chromium-browser"
    assert selected.browser_context_revision == browser_revision(settings, profile.key)
    assert selected.protocol_capabilities == ("browser-page", "http-media")
    assert selected.generation_id != primary.generation_id
    assert selected.credential_version_id is None
    assert await store.validate_context(profile, selected) == selected


@pytest.mark.parametrize("selected_id", ["missing-route", BROWSER.strategy_id])
async def test_missing_or_disabled_selected_route_never_uses_primary(
    tmp_path, selected_id
):
    profile = _profile(replace(BROWSER, enabled=False))
    store = ProviderSessionStore(_settings(tmp_path))
    with pytest.raises(RunnerFailure) as error:
        await store.context_for(profile, strategy_id=selected_id)
    assert error.value.code == "provider_unsupported"


async def test_missing_browser_does_not_fall_back_to_http(tmp_path):
    settings = _settings(tmp_path).model_copy(update={"runner_browser_enabled": False})
    store = ProviderSessionStore(settings)
    with pytest.raises(RunnerFailure) as error:
        await store.context_for(_profile(), strategy_id=BROWSER.strategy_id)
    assert error.value.code == "browser_unavailable"
    assert error.value.failure.phase is FailurePhase.PREPARE_CONTEXT


@pytest.mark.parametrize(
    ("handoff", "protocols"),
    [
        (MediaHandoff.BROWSER_TRANSFERABLE, ("browser-media", "browser-page")),
        (MediaHandoff.UNSUPPORTED, ("browser-page",)),
    ],
)
async def test_browser_context_does_not_advertise_undeclared_http_handoff(
    tmp_path, handoff, protocols
):
    store = ProviderSessionStore(_settings(tmp_path))
    selected = await store.context_for(
        _profile(replace(BROWSER, media_handoff=handoff)),
        strategy_id=BROWSER.strategy_id,
    )
    assert selected.protocol_capabilities == protocols


async def test_service_checks_selected_plan_before_context_preparation(
    tmp_path, monkeypatch
):
    profile, settings = _profile(), _settings(tmp_path)
    monkeypatch.setattr(
        service_module,
        "provider_request",
        lambda url: ProviderRequest(url, url, profile),
    )
    runner = MediaRunnerService(settings)
    revision = resolution_capability(profile, settings).revision
    selected = await runner.context(
        URL, strategy_id=BROWSER.strategy_id, plan_revision=revision
    )
    assert selected.strategy_id == BROWSER.strategy_id
    with pytest.raises(RunnerFailure) as error:
        await runner.context(
            URL, strategy_id=BROWSER.strategy_id, plan_revision="0" * 64
        )
    assert error.value.code == "context_changed"
    await runner.close()


async def test_selected_route_cannot_change_access_mode(tmp_path):
    store = ProviderSessionStore(_settings(tmp_path))
    with pytest.raises(RunnerFailure) as error:
        await store.context_for(
            _profile(),
            access_mode=ProviderAccessMode.OPERATOR_MANAGED,
            strategy_id=BROWSER.strategy_id,
        )
    assert error.value.code == "provider_session_not_allowed"
