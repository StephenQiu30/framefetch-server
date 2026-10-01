from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.services.provider_failures import FailureClass, FailureScope
from app.services.provider_types import ExecutionContext
from app.workers.runner import browser_runtime
from app.workers.runner.browser_runtime import (
    BrowserRuntime,
    browser_revision,
    leased_browser_cookies,
)
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import provider_profile
from app.workers.runner.settings import RunnerSettings


def configured(tmp_path: Path, **overrides) -> RunnerSettings:
    return RunnerSettings(
        runner_hmac_secret="r" * 32,
        runner_egress_proxy="http://egress-proxy:3128",
        runner_workspace_root=tmp_path / "work",
        runner_browser_profile_root=tmp_path / "profiles",
        runner_browser_temp_root=tmp_path / "temporary",
        runner_browser_lock_wait_seconds=0.02,
        runner_browser_enabled=True,
        **overrides,
    )


def anonymous_context() -> ExecutionContext:
    return ExecutionContext(
        provider_key="youtube",
        registry_revision="test",
        resolved_layer="L3",
        client="test",
        engine_revision="test",
        egress_route="default",
        egress_revision="test",
        egress_class="unknown",
        egress_observed_ip=None,
        identity_used=False,
        identity_digest=None,
        browser_context_kind="anonymous",
    )


class FakeChromium:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.contexts: list[SimpleNamespace] = []
        self.cleanup_started = asyncio.Event()
        self.cleanup_allowed = asyncio.Event()
        self.cleanup_allowed.set()
        self.drivers_closed = 0

    async def launch_persistent_context(self, directory: str, **options):
        self.calls.append((directory, options))
        context = SimpleNamespace(
            browser=SimpleNamespace(version=browser_runtime.CHROMIUM_VERSION),
            pages=[SimpleNamespace()],
            closed=False,
        )

        async def close():
            self.cleanup_started.set()
            await self.cleanup_allowed.wait()
            context.closed = True

        context.close = close
        context.set_default_timeout = lambda _: None
        self.contexts.append(context)
        return context

    @asynccontextmanager
    async def driver(self):
        try:
            yield SimpleNamespace(chromium=self)
        finally:
            self.drivers_closed += 1


@pytest.fixture
def chromium(monkeypatch: pytest.MonkeyPatch) -> FakeChromium:
    fake = FakeChromium()
    monkeypatch.setattr(browser_runtime, "async_playwright", fake.driver)
    return fake


async def test_disabled_browser_has_no_resources_or_effect_on_http(tmp_path, chromium):
    settings = configured(tmp_path).model_copy(update={"runner_browser_enabled": False})
    runtime = BrowserRuntime(settings)
    profile = provider_profile("https://www.youtube.com/watch?v=owned")
    with pytest.raises(RunnerFailure) as caught:
        async with runtime.operation(profile, anonymous_context()):
            pytest.fail("disabled runtime started")
    assert caught.value.failure.failure_class is FailureClass.RUNTIME_UNAVAILABLE
    assert caught.value.failure.scope is FailureScope.RUNTIME
    assert chromium.calls == []
    assert not settings.runner_browser_profile_root.exists()
    assert not settings.runner_browser_temp_root.exists()


async def test_anonymous_context_is_temporary_and_bound_to_provider_proxy(
    tmp_path, chromium
):
    settings = configured(
        tmp_path,
        runner_provider_egress_proxies={"youtube": "http://youtube-egress:3128"},
    )
    runtime = BrowserRuntime(settings)
    profile = provider_profile("https://www.youtube.com/watch?v=owned")
    async with runtime.operation(profile, anonymous_context()) as operation:
        assert operation.revision == browser_revision(settings, "youtube")
        directory, options = chromium.calls[0]
        assert Path(directory).is_dir()
        assert options["proxy"] == {"server": "http://youtube-egress:3128"}
        assert "--proxy-bypass-list=<-loopback>" in options["args"]
        assert options["headless"] is True
        assert options["accept_downloads"] is False
        assert options["service_workers"] == "block"
    assert Path(directory).exists()
    assert chromium.contexts[0].closed
    assert chromium.drivers_closed == 1
    await runtime.close()


async def test_same_runtime_cannot_start_a_second_holder(tmp_path, chromium):
    runtime = BrowserRuntime(configured(tmp_path))
    profile = provider_profile("https://www.youtube.com/watch?v=owned")
    async with runtime.operation(profile, anonymous_context()):
        with pytest.raises(RunnerFailure) as caught:
            async with runtime.operation(profile, anonymous_context()):
                pytest.fail("second browser started")
        assert caught.value.code == "browser_capacity_exhausted"
        assert caught.value.failure.scope is FailureScope.RUNTIME
        assert len(chromium.calls) == 1


async def test_cancel_does_not_release_profile_or_ack_before_native_cleanup(
    tmp_path, chromium
):
    settings = configured(tmp_path)
    runtime = BrowserRuntime(settings)
    profile = provider_profile("https://www.youtube.com/watch?v=owned")
    started = asyncio.Event()
    chromium.cleanup_allowed.clear()

    async def execute():
        async with runtime.operation(profile, anonymous_context()):
            started.set()
            await asyncio.Event().wait()

    owner = asyncio.create_task(execute())
    await started.wait()
    owner.cancel()
    await chromium.cleanup_started.wait()
    assert not owner.done()
    with pytest.raises(RunnerFailure, match="browser capacity exhausted"):
        async with runtime.operation(profile, anonymous_context()):
            pytest.fail("cleanup still holds browser")
    chromium.cleanup_allowed.set()
    with pytest.raises(asyncio.CancelledError):
        await owner
    assert chromium.contexts[0].closed
    async with runtime.operation(profile, anonymous_context()):
        pass


async def test_native_profile_uses_cross_runtime_os_lock_and_keeps_state(
    tmp_path, chromium
):
    settings = configured(tmp_path)
    first, second = BrowserRuntime(settings), BrowserRuntime(settings)
    profile = provider_profile("https://www.youtube.com/watch?v=owned")
    context = anonymous_context()
    async with first.operation(profile, context):
        directory = Path(chromium.calls[0][0])
        marker = directory / "native-state"
        marker.write_text("retained by browser")
        with pytest.raises(RunnerFailure) as caught:
            async with second.operation(profile, context):
                pytest.fail("persistent profile has two holders")
        assert caught.value.code == "browser_capacity_exhausted"
    assert marker.exists()
    async with second.operation(profile, context):
        assert chromium.calls[-1][0] == str(directory)
        assert marker.read_text() == "retained by browser"


def test_approved_lease_preserves_native_cookie_attributes_and_domain_scope(tmp_path):
    jar = tmp_path / "cookie"
    jar.write_bytes(
        b"# Netscape HTTP Cookie File\n"
        b"#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tfixture\n"
    )
    profile = provider_profile("https://www.youtube.com/watch?v=owned")
    cookies = leased_browser_cookies(jar, profile)
    assert cookies == [
        {
            "domain": ".youtube.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "name": "SID",
            "value": "fixture",
        }
    ]
    jar.write_bytes(jar.read_bytes().replace(b".youtube.com", b".unapproved.example"))
    with pytest.raises(RunnerFailure, match="credential rejected"):
        leased_browser_cookies(jar, profile)


def test_browser_revision_changes_only_with_execution_configuration(tmp_path):
    first = configured(tmp_path)
    assert browser_revision(first, "youtube") == browser_revision(first, "youtube")
    changed = first.model_copy(
        update={"runner_egress_proxy": "http://other-route:3128"}
    )
    assert browser_revision(first, "youtube") != browser_revision(changed, "youtube")


async def test_page_adapter_error_is_not_rewritten_as_browser_startup_failure(
    tmp_path, chromium
):
    runtime = BrowserRuntime(configured(tmp_path))
    profile = provider_profile("https://www.youtube.com/watch?v=owned")
    failure = browser_runtime.Error("page structure changed")
    with pytest.raises(browser_runtime.Error) as caught:
        async with runtime.operation(profile, anonymous_context()):
            raise failure
    assert caught.value is failure
    assert chromium.contexts[0].closed
