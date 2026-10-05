from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.services.provider_failures import FailureClass
from app.workers.runner import browser_runtime
from app.workers.runner.browser_runtime import (
    BrowserRuntime,
    browser_revision,
    leased_browser_cookies,
)
from app.workers.runner.engine import identity
from app.workers.runner.engine.layers.base import LayerFailure
from app.workers.runner.engine.layers.browser import BrowserLayer
from app.workers.runner.engine.run_context import ResolutionSource
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import (
    current_provider_registry,
    provider_request,
)
from app.workers.runner.service import MediaRunnerService
from app.workers.runner.settings import RunnerSettings
from app.workers.runner.workspace import WorkspaceLimits, WorkspaceManager
from helpers import run_context


def configured(tmp_path, **overrides):
    return RunnerSettings(
        runner_hmac_secret="r" * 32,
        runner_egress_proxy="http://egress-proxy:3128",
        runner_workspace_root=tmp_path / "work",
        runner_browser_profile_root=tmp_path / "profiles",
        runner_browser_temp_root=tmp_path / "temporary",
        runner_browser_enabled=True,
        **overrides,
    )


class FakePage:
    def __init__(self, context):
        self.context = context

    async def close(self):
        if self in self.context.pages:
            self.context.pages.remove(self)

    def remove_listener(self, event, callback):
        pass


class FakeContext:
    def __init__(self, chromium):
        self.chromium = chromium
        self.browser = SimpleNamespace(version=browser_runtime.CHROMIUM_VERSION)
        self.pages = []
        self.closed = False
        self.injected = []

    async def new_page(self):
        page = FakePage(self)
        self.pages.append(page)
        return page

    def set_default_timeout(self, _):
        pass

    async def add_cookies(self, cookies):
        self.injected.extend(cookies)

    async def cookies(self):
        return self.injected

    async def close(self):
        self.chromium.cleanup_started.set()
        await self.chromium.cleanup_allowed.wait()
        self.closed = True
        self.pages.clear()


class FakeChromium:
    def __init__(self):
        self.calls = []
        self.contexts = []
        self.cleanup_started = asyncio.Event()
        self.cleanup_allowed = asyncio.Event()
        self.cleanup_allowed.set()

    async def launch_persistent_context(self, directory, **options):
        self.calls.append((directory, options))
        context = FakeContext(self)
        self.contexts.append(context)
        return context

    @asynccontextmanager
    async def driver(self):
        yield SimpleNamespace(chromium=self)


@pytest.fixture
def chromium(monkeypatch):
    fake = FakeChromium()
    monkeypatch.setattr(browser_runtime, "async_playwright", fake.driver)
    monkeypatch.setattr(browser_runtime, "_is_tmpfs", lambda _: True)
    return fake


def profile(key="douyin"):
    return current_provider_registry().profile_for_key(key)


async def test_disabled_runtime_never_touches_profile(tmp_path, chromium):
    settings = configured(tmp_path).model_copy(update={"runner_browser_enabled": False})
    runtime = BrowserRuntime(settings)
    with pytest.raises(RunnerFailure):
        await runtime.acquire(profile(), ctx=run_context(settings))
    assert not chromium.calls
    assert not settings.runner_browser_profile_root.exists()


async def test_anonymous_reuses_platform_context_and_never_injects_cookie(
    tmp_path, chromium
):
    settings = configured(tmp_path)
    runtime = BrowserRuntime(settings)
    ctx = run_context(settings)
    first = await runtime.acquire(profile(), ctx=ctx)
    assert await first.cookies() == []
    assert not chromium.contexts[0].injected
    directory, options = chromium.calls[0]
    assert Path(directory).is_relative_to(
        settings.runner_browser_profile_root / "anonymous"
    )
    assert options["proxy"] == {"server": ctx.egress.proxy_url}
    assert options["service_workers"] == "block"
    assert "--autoplay-policy=user-gesture-required" in options["args"]
    await first.close()
    assert not first.context.closed and not first.context.pages
    second = await runtime.acquire(profile(), ctx=ctx)
    other = await runtime.acquire(profile("xiaohongshu"), ctx=ctx)
    assert second.context is first.context and other.context is not first.context
    await second.close()
    await other.close()
    await runtime.close()
    assert all(c.closed for c in chromium.contexts)


async def test_platform_queue_counts_against_deadline(tmp_path, chromium):
    runtime = BrowserRuntime(configured(tmp_path))
    ctx = run_context(configured(tmp_path))
    first = await runtime.acquire(profile(), ctx=ctx)
    pending = asyncio.create_task(runtime.acquire(profile(), ctx=ctx))
    await asyncio.sleep(0.01)
    assert not pending.done() and len(chromium.calls) == 1
    await first.close()
    second = await pending
    with pytest.raises(RunnerFailure, match="inspection timeout"):
        await runtime.acquire(
            profile(),
            ctx=replace(ctx, deadline=datetime.now(UTC) + timedelta(seconds=0.01)),
        )
    await second.close()
    await runtime.close()


async def test_idle_ten_minutes_releases_native_context_and_os_lock(
    tmp_path, chromium, monkeypatch
):
    settings = configured(tmp_path)
    first, second = BrowserRuntime(settings), BrowserRuntime(settings)
    ctx = run_context(settings)
    operation = await first.acquire(profile(), ctx=ctx)
    assert first.IDLE_SECONDS == 600
    monkeypatch.setattr(first, "IDLE_SECONDS", 0.05)
    await operation.close()
    with pytest.raises(RunnerFailure, match="browser capacity exhausted"):
        await second.acquire(profile(), ctx=ctx)
    await asyncio.wait_for(chromium.cleanup_started.wait(), 1)
    await asyncio.sleep(0.01)
    assert operation.context.closed
    fresh = await second.acquire(profile(), ctx=ctx)
    assert fresh.context is not operation.context
    await fresh.close()
    await first.close()
    await second.close()


@pytest.mark.parametrize("terminal", ["success", "failure", "cancel"])
async def test_login_context_task_isolation_and_terminal_destruction(
    tmp_path, chromium, monkeypatch, terminal
):
    monkeypatch.setattr(identity, "validate_cookie_file", lambda _: None)
    jar = tmp_path / "identity.txt"
    jar.write_bytes(
        b"# Netscape HTTP Cookie File\n"
        b".douyin.com\tTRUE\t/\tTRUE\t0\tsessionid\tmock-account\n"
    )
    ctx = run_context(configured(tmp_path)).with_material(
        identity=identity.IdentityMaterial(jar, "mock-digest")
    )
    runtime = BrowserRuntime(configured(tmp_path))
    started = asyncio.Event()
    operation = None

    async def execute():
        nonlocal operation
        operation = await runtime.acquire(profile(), ctx=ctx)
        try:
            started.set()
            if terminal == "cancel":
                await asyncio.Event().wait()
            if terminal == "failure":
                raise ValueError("failed")
        finally:
            await operation.close()

    task = asyncio.create_task(execute())
    await started.wait()
    if terminal == "cancel":
        chromium.cleanup_allowed.clear()
        task.cancel()
        await chromium.cleanup_started.wait()
        assert not task.done()
        assert Path(chromium.calls[0][0]).exists()
        chromium.cleanup_allowed.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif terminal == "failure":
        with pytest.raises(ValueError):
            await task
    else:
        await task
    assert operation.context.closed
    assert not Path(chromium.calls[0][0]).exists()
    assert chromium.contexts[0].injected[0]["name"] == "sessionid"
    anonymous = await runtime.acquire(profile(), ctx=run_context(configured(tmp_path)))
    assert await anonymous.cookies() == []
    await anonymous.close()
    await runtime.close()


async def test_cancel_anonymous_destroys_before_next_owner(tmp_path, chromium):
    runtime = BrowserRuntime(configured(tmp_path))
    ctx = run_context(configured(tmp_path))
    ready = asyncio.Event()

    async def execute():
        operation = await runtime.acquire(profile(), ctx=ctx)
        try:
            ready.set()
            await asyncio.Event().wait()
        finally:
            await operation.close()

    owner = asyncio.create_task(execute())
    await ready.wait()
    chromium.cleanup_allowed.clear()
    owner.cancel()
    await chromium.cleanup_started.wait()
    pending = asyncio.create_task(runtime.acquire(profile(), ctx=ctx))
    await asyncio.sleep(0.01)
    assert not owner.done() and not pending.done()
    chromium.cleanup_allowed.set()
    with pytest.raises(asyncio.CancelledError):
        await owner
    next_operation = await pending
    assert chromium.contexts[0].closed
    await next_operation.close()
    await runtime.close()


def test_cookie_attributes_and_domain_scope(tmp_path):
    jar = tmp_path / "cookie"
    jar.write_bytes(
        b"# Netscape HTTP Cookie File\n"
        b"#HttpOnly_.douyin.com\tTRUE\t/\tTRUE\t0\tSID\tmock\n"
    )
    assert leased_browser_cookies(jar, profile())[0]["httpOnly"] is True
    jar.write_bytes(jar.read_bytes().replace(b".douyin.com", b".example.org"))
    with pytest.raises(RunnerFailure):
        leased_browser_cookies(jar, profile())


async def test_page_release_failure_still_destroys_and_releases_holder(
    tmp_path, chromium
):
    runtime = BrowserRuntime(configured(tmp_path))
    ctx = run_context(configured(tmp_path))
    operation = await runtime.acquire(profile(), ctx=ctx)

    async def fail():
        raise browser_runtime.Error("connection closed")

    operation.page.close = fail
    with pytest.raises(browser_runtime.Error):
        await operation.close()
    assert operation.context.closed and not runtime._residents
    next_operation = await runtime.acquire(profile(), ctx=ctx)
    await next_operation.close()
    await runtime.close()


async def test_anonymous_acquisition_rejects_bare_cookie_file(
    tmp_path, chromium, monkeypatch
):
    monkeypatch.setattr(identity, "validate_cookie_file", lambda _: None)
    runtime = BrowserRuntime(configured(tmp_path))
    ctx = replace(run_context(configured(tmp_path)), cookie_file=tmp_path / "account")
    with pytest.raises(RunnerFailure):
        await runtime.acquire(profile(), ctx=ctx)
    assert chromium.calls == []


@pytest.mark.parametrize("filename", ["docker-compose.yml", "docker-compose-prod.yml"])
def test_native_anonymous_volume_and_private_task_tmpfs_ownership(filename):
    import yaml

    compose = yaml.safe_load(
        (Path(__file__).resolve().parents[5] / filename).read_text()
    )
    runner = compose["services"]["session-runner"]
    assert "browser_profiles:/var/lib/video-browser" in runner["volumes"]
    mounts = {line.split(":", 1)[0]: line.split(":", 1)[1] for line in runner["tmpfs"]}
    for root in ("/tmp/video-browser", "/tmp/framefetch-identity"):
        flags = mounts[root].split(",")
        assert {"rw", "noexec", "nosuid", "uid=10001", "gid=10001", "mode=0700"} <= set(
            flags
        )
        assert any(flag.startswith("size=") for flag in flags)


def test_browser_revision_changes_only_with_execution_configuration(tmp_path):
    first = configured(tmp_path)
    assert browser_revision(run_context(first, "youtube").egress) == browser_revision(
        run_context(first, "youtube").egress
    )
    changed = first.model_copy(
        update={"runner_global_egress_proxy": "http://other-route:3128"}
    )
    assert browser_revision(run_context(first, "youtube").egress) != browser_revision(
        run_context(changed, "youtube").egress
    )


async def test_page_navigation_failure_destroys_resident_before_next_acquisition(
    tmp_path, chromium, monkeypatch
):
    settings = configured(tmp_path)
    service = MediaRunnerService(settings)
    runtime = service._browser
    ctx = run_context(settings, "douyin")
    request = provider_request("https://www.douyin.com/video/1234567890")
    workspace = WorkspaceManager(
        settings.runner_workspace_root, WorkspaceLimits()
    ).create("page_failure")
    source = ResolutionSource(
        request,
        workspace,
        service._inspection,
        service._context(request),
        ctx,
    )

    async def navigate(operation, url):
        raise browser_runtime.Error("page structure changed")

    monkeypatch.setattr(browser_runtime.BrowserOperation, "navigate", navigate)
    try:
        with pytest.raises(LayerFailure) as caught:
            await BrowserLayer().resolve(source, ctx)
        failure = caught.value.failure
        assert failure.failure_class is FailureClass.CHALLENGE
        assert failure.evidence["cause_code"] == "page_navigation_failed"
        assert chromium.contexts[0].closed
        assert not runtime._residents
        next_operation = await runtime.acquire(profile(), ctx=ctx)
        assert next_operation.context is not chromium.contexts[0]
        await next_operation.close()
    finally:
        await service.close()
        workspace.cleanup()


async def test_browser_launch_uses_injected_egress_only(tmp_path, chromium):
    from app.workers.runner.engine.egress import EgressBinding

    settings = configured(
        tmp_path, runner_global_egress_proxy="http://youtube-egress:3129"
    )
    runtime = BrowserRuntime(settings)
    ctx = replace(
        run_context(settings, "youtube"),
        egress=EgressBinding(
            "global_residential",
            "http://browser-binding:3128",
            "injected-revision",
            "residential",
            None,
        ),
    )
    assert ctx.egress.proxy_url not in (
        settings.runner_egress_proxy,
        settings.runner_global_egress_proxy,
    )
    operation = await runtime.acquire(profile("youtube"), ctx=ctx)
    assert operation.revision == browser_revision(ctx.egress)
    assert chromium.calls[-1][1]["proxy"] == {"server": ctx.egress.proxy_url}
    assert "--proxy-bypass-list=<-loopback>" in chromium.calls[-1][1]["args"]
    assert chromium.calls[-1][1]["headless"] is True
    assert chromium.calls[-1][1]["accept_downloads"] is True
    await operation.close()
    await runtime.close()


async def test_route_upstream_revision_replaces_resident_browser(tmp_path, chromium):
    settings = configured(tmp_path, egress_global_upstream_host="residential-first")
    runtime = BrowserRuntime(settings)
    ctx = run_context(settings, "youtube")
    first = await runtime.acquire(profile("youtube"), ctx=ctx)
    assert chromium.calls[-1][1]["proxy"] == {
        "server": settings.runner_global_egress_proxy
    }
    await first.close()
    assert not first.context.closed
    # R1 upstream changes must invalidate R3's persistent context even when
    # Squid's listener URL stays the same; observational IP alone does not.
    observed_ctx = replace(ctx, egress=replace(ctx.egress, observed_ip="8.8.8.8"))
    same = await runtime.acquire(profile("youtube"), ctx=observed_ctx)
    assert same.context is first.context
    await same.close()
    changed = settings.model_copy(
        update={"egress_global_upstream_host": "residential-next"}
    )
    new_ctx = run_context(changed, "youtube")
    assert new_ctx.egress.proxy_url == ctx.egress.proxy_url
    assert new_ctx.egress.revision != ctx.egress.revision
    next_operation = await runtime.acquire(profile("youtube"), ctx=new_ctx)
    assert first.context.closed
    assert next_operation.context is not first.context
    assert next_operation.revision != first.revision
    assert chromium.calls[-1][1]["proxy"] == {"server": new_ctx.egress.proxy_url}
    await next_operation.close()
    await runtime.close()


@pytest.fixture
def cookie_identity(monkeypatch):
    monkeypatch.setattr(identity, "validate_cookie_file", lambda _: None)
    monkeypatch.setattr(
        browser_runtime,
        "leased_browser_cookies",
        lambda _file, _profile: [
            {
                "domain": ".douyin.com",
                "path": "/",
                "name": "sessionid",
                "value": "synthetic-cookie",
                "secure": True,
                "httpOnly": True,
            }
        ],
    )


def cookie_context(settings):
    return run_context(settings, "douyin").with_material(
        identity=identity.IdentityMaterial(
            settings.runner_workspace_root.parent / "synthetic-cookie", "a" * 64
        )
    )


@pytest.mark.parametrize("terminal", ["success", "failure", "cancel"])
async def test_cookie_identity_uses_private_tmpfs_and_terminal_destruction(
    tmp_path, chromium, cookie_identity, terminal
):
    settings = configured(tmp_path)
    runtime = BrowserRuntime(settings)
    ctx = cookie_context(settings)
    ready = asyncio.Event()
    operation = None

    async def execute():
        nonlocal operation
        operation = await runtime.acquire(profile("douyin"), ctx=ctx)
        try:
            ready.set()
            if terminal == "cancel":
                await asyncio.Event().wait()
            if terminal == "failure":
                raise ValueError("synthetic failure")
        finally:
            await operation.close()

    owner = asyncio.create_task(execute())
    await ready.wait()
    directory = Path(chromium.calls[0][0])
    assert directory.is_relative_to(settings.runner_browser_temp_root)
    assert directory.stat().st_mode & 0o777 == 0o700
    assert not settings.runner_browser_profile_root.exists()
    assert ctx.cookie_file is not None
    assert chromium.contexts[0].injected[0]["name"] == "sessionid"
    if terminal == "cancel":
        chromium.cleanup_allowed.clear()
        owner.cancel()
        await chromium.cleanup_started.wait()
        assert not owner.done() and directory.exists()
        chromium.cleanup_allowed.set()
        with pytest.raises(asyncio.CancelledError):
            await owner
    elif terminal == "failure":
        with pytest.raises(ValueError, match="synthetic failure"):
            await owner
    else:
        await owner
    assert operation.context.closed and not directory.exists()
    assert not runtime._residents
    await runtime.close()


async def test_cookie_identity_rejects_non_tmpfs_before_browser_launch(
    tmp_path, chromium, cookie_identity, monkeypatch
):
    settings = configured(tmp_path)
    monkeypatch.setattr(browser_runtime, "_is_tmpfs", lambda _: False)
    runtime = BrowserRuntime(settings)
    with pytest.raises(RunnerFailure):
        await runtime.acquire(profile("douyin"), ctx=cookie_context(settings))
    assert not chromium.calls
    assert list(settings.runner_browser_temp_root.iterdir()) == []
    assert not settings.runner_browser_profile_root.exists()
    await runtime.close()


@pytest.mark.parametrize("key", ["douyin", "wechat_channels"])
async def test_request_identity_cannot_enter_owned_browser(tmp_path, chromium, key):
    settings = configured(tmp_path)
    runtime = BrowserRuntime(settings)
    with pytest.raises(RunnerFailure):
        await runtime.acquire(
            profile(key),
            ctx=run_context(settings, key).with_material(
                identity=identity.YuanbaoRequestIdentity("a" * 64)
            ),
        )
    assert not chromium.calls
    await runtime.close()


async def test_cookie_identity_cannot_be_used_for_native_page_platform(
    tmp_path, chromium, monkeypatch
):
    monkeypatch.setattr(identity, "validate_cookie_file", lambda _: None)
    settings = configured(tmp_path)
    ctx = run_context(settings).with_material(
        identity=identity.IdentityMaterial(tmp_path / "synthetic-cookie", "mock-digest")
    )
    runtime = BrowserRuntime(settings)
    with pytest.raises(RunnerFailure):
        await runtime.acquire(profile("wechat_channels"), ctx=ctx)
    assert not chromium.calls
    await runtime.close()


@pytest.mark.parametrize("authenticated", [False, True])
async def test_repeated_cancellation_waits_for_native_context_close(
    tmp_path, chromium, cookie_identity, authenticated
):
    settings = configured(tmp_path)
    runtime = BrowserRuntime(settings)
    key = "douyin"
    ctx = cookie_context(settings) if authenticated else run_context(settings)
    acquired = asyncio.Event()
    cleanup_requested = asyncio.Event()

    async def execute():
        operation = await runtime.acquire(profile(key), ctx=ctx)
        acquired.set()
        await cleanup_requested.wait()
        if authenticated:
            await operation.close()
        else:
            await operation.abort()

    chromium.cleanup_allowed.clear()
    owner = asyncio.create_task(execute())
    try:
        await asyncio.wait_for(acquired.wait(), 1)
        cleanup_requested.set()
        await asyncio.wait_for(chromium.cleanup_started.wait(), 1)
        owner.cancel()
        await asyncio.sleep(0)
        owner.cancel()
        await asyncio.sleep(0)
        directory = Path(chromium.calls[0][0])
        assert not owner.done()
        assert directory.exists()
        assert not chromium.contexts[0].closed
        chromium.cleanup_allowed.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(owner, 1)
        assert chromium.contexts[0].closed
        if authenticated:
            assert not directory.exists()
        assert not runtime._releases and not runtime._owners
    finally:
        cleanup_requested.set()
        chromium.cleanup_allowed.set()
        await asyncio.wait_for(asyncio.gather(owner, return_exceptions=True), 1)
        await runtime.close()


@pytest.mark.parametrize("authenticated", [False, True])
async def test_launch_close_error_still_releases_private_state_and_os_lock(
    tmp_path, chromium, cookie_identity, monkeypatch, authenticated
):
    settings = configured(tmp_path)
    runtime = BrowserRuntime(settings)
    key = "douyin"
    ctx = cookie_context(settings) if authenticated else run_context(settings)
    original_close = FakeContext.close
    original_inject = FakeContext.add_cookies
    original_launch = chromium.launch_persistent_context

    async def fail_inject(context, cookies):
        raise browser_runtime.Error("synthetic initialization error: synthetic-token")

    async def fail_close(context):
        raise browser_runtime.Error("synthetic close error: synthetic-token")

    async def invalid_runtime(directory, **options):
        context = await original_launch(directory, **options)
        context.browser.version = "synthetic-incompatible-runtime"
        return context

    monkeypatch.setattr(FakeContext, "close", fail_close)
    if authenticated:
        monkeypatch.setattr(FakeContext, "add_cookies", fail_inject)
    else:
        monkeypatch.setattr(chromium, "launch_persistent_context", invalid_runtime)
    try:
        with pytest.raises(RunnerFailure) as caught:
            await asyncio.wait_for(runtime.acquire(profile(key), ctx=ctx), 1)
        assert "synthetic-token" not in str(caught.value)
        assert not runtime._releases and not runtime._owners
        if authenticated:
            assert not list(settings.runner_browser_temp_root.iterdir())
        monkeypatch.setattr(FakeContext, "close", original_close)
        monkeypatch.setattr(FakeContext, "add_cookies", original_inject)
        monkeypatch.setattr(chromium, "launch_persistent_context", original_launch)
        # A second runtime must be able to obtain the released process lock.
        fresh_runtime = BrowserRuntime(settings)
        try:
            operation = await asyncio.wait_for(
                fresh_runtime.acquire(profile(key), ctx=ctx), 1
            )
            await operation.close()
        finally:
            await fresh_runtime.close()
    finally:
        await runtime.close()


async def test_cleanup_cancellation_itself_propagates_without_retry_loop():
    async def cancelled_cleanup():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(browser_runtime._finish(cancelled_cleanup()), 1)


async def test_runner_lifespan_clears_browser_state_before_accepting_requests(
    tmp_path, monkeypatch
):
    from app.workers.runner import main

    calls = []
    monkeypatch.setattr(
        main, "initialize_identity_tmpfs", lambda _: calls.append("identity")
    )
    monkeypatch.setattr(
        browser_runtime, "initialize_browser_tmpfs", lambda _: calls.append("browser")
    )
    app = main.create_app(configured(tmp_path), service=SimpleNamespace())
    async with app.router.lifespan_context(app):
        assert calls == ["identity", "browser"]


def test_browser_startup_removes_only_private_crash_state(tmp_path, monkeypatch):
    root = tmp_path / "temporary"
    root.mkdir(mode=0o700)
    stale = root / "wechat_channels-stale"
    stale.mkdir()
    (stale / "Local Storage").write_text("synthetic stale account")
    outside = tmp_path / "outside"
    outside.write_text("keep")
    (root / "symlink").symlink_to(outside)
    monkeypatch.setattr(browser_runtime, "_is_tmpfs", lambda _: True)
    browser_runtime.initialize_browser_tmpfs(root)
    assert not list(root.iterdir()) and outside.read_text() == "keep"


@pytest.mark.parametrize("kind", ["non_tmpfs", "ancestor_symlink", "public_mode"])
def test_private_browser_root_rejects_untrusted_storage(tmp_path, monkeypatch, kind):
    root = tmp_path / "temporary"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(browser_runtime, "_is_tmpfs", lambda _: kind != "non_tmpfs")
    if kind == "ancestor_symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        root = alias / "temporary"
    elif kind == "public_mode":
        root.chmod(0o755)
    with pytest.raises(RunnerFailure):
        browser_runtime.initialize_browser_tmpfs(root)
