"""Design 17 recovery scopes, shared deadlines and material ownership."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from app.services.provider_failures import FailureClass
from app.services.provider_types import Layer, ProviderIdentity
from app.workers.runner.engine import identity
from app.workers.runner.engine.identity import IdentityMaterial
from app.workers.runner.engine.ladder import LAYER_TABLE, close_material, run_ladder
from app.workers.runner.engine.layers.base import LayerFailure
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.service import MediaRunnerService
from helpers import settings
from test_engine_skeleton import source_for
from test_p1_wiring import Browser, resolved


@pytest.fixture
def source(tmp_path):
    item = source_for(MediaRunnerService(settings(tmp_path)), tmp_path)
    yield item
    item.workspace.cleanup()


def layers(source, *keys, identity=ProviderIdentity.NONE):
    profile = replace(source.request.profile, ladder=keys, identity=identity)
    return replace(source, request=replace(source.request, profile=profile))


def dispatch(monkeypatch, sequence, *, after=None):
    calls = []

    class Scripted:
        async def resolve(self, source, ctx):
            key = source.execution_context.resolved_layer
            calls.append((key, ctx.identity))
            value = sequence[key].pop(0)
            if isinstance(value, FailureClass):
                raise LayerFailure(value, "none", {"kind": "unknown"})
            if isinstance(value, BaseException):
                raise value
            return (
                resolved(ctx, client=source.execution_context.client)
                if after is None
                else after(ctx)
            )

    for key in sequence:
        monkeypatch.setitem(LAYER_TABLE, key, Scripted)
    return calls


@pytest.mark.parametrize(
    "kind",
    [
        FailureClass.NETWORK_BLOCKED,
        FailureClass.CHALLENGE,
        FailureClass.EXTRACTOR_BROKEN,
        FailureClass.FORMAT_UNAVAILABLE,
    ],
)
async def test_next_layer_once_and_terminal_history(source, monkeypatch, kind, caplog):
    caplog.set_level("WARNING", logger="app.workers.runner.engine.ladder")
    source = layers(source, Layer.L1, Layer.L2, Layer.L3)
    calls = dispatch(monkeypatch, {"L1": [kind], "L2": [kind], "L3": [kind]})
    with pytest.raises(RunnerFailure) as caught:
        await run_ladder(source, source.request.profile, source.run_context.deadline)
    assert [key for key, _ in calls] == ["L1", "L2", "L3"]
    assert [failure.layer for failure in caught.value.failures] == ["L1", "L2", "L3"]
    assert "Stopped at L3" in caught.value.failure.summary
    assert caplog.text.count("resolver failed task=") == 3


@pytest.mark.parametrize(
    "kind",
    [
        FailureClass.IDENTITY_UNAVAILABLE,
        FailureClass.CONTENT_UNAVAILABLE,
        FailureClass.CONTENT_PROTECTED,
        FailureClass.INVALID_INPUT,
        FailureClass.CONTEXT_CHANGED,
        FailureClass.LOGIN_REQUIRED,
    ],
)
async def test_terminal_classes_do_not_retry_or_advance(source, monkeypatch, kind):
    source = layers(source, Layer.L1, Layer.L2)
    calls = dispatch(monkeypatch, {"L1": [kind], "L2": [None]})
    with pytest.raises(RunnerFailure) as caught:
        await run_ladder(source, source.request.profile, source.run_context.deadline)
    assert caught.value.failure.failure_class is kind and len(calls) == 1


async def test_transient_retry_is_per_layer(source, monkeypatch):
    source = layers(source, Layer.L1, Layer.L2)
    calls = dispatch(
        monkeypatch,
        {
            "L1": [FailureClass.TRANSIENT, FailureClass.CHALLENGE],
            "L2": [FailureClass.TRANSIENT, None],
        },
    )
    result = await run_ladder(
        source, source.request.profile, source.run_context.deadline
    )
    assert [key for key, _ in calls] == ["L1", "L1", "L2", "L2"]
    assert len(result.failures) == 3


async def test_second_transient_stops_same_layer(source, monkeypatch):
    source = layers(source, Layer.L1, Layer.L2)
    calls = dispatch(monkeypatch, {"L1": [FailureClass.TRANSIENT] * 2, "L2": [None]})
    with pytest.raises(RunnerFailure):
        await run_ladder(source, source.request.profile, source.run_context.deadline)
    assert [key for key, _ in calls] == ["L1", "L1"]


@pytest.mark.parametrize(
    "kind", [FailureClass.RUNTIME_UNAVAILABLE, FailureClass.RATE_LIMITED]
)
async def test_retry_allowance_is_shared_by_layers(source, monkeypatch, kind):
    source = layers(source, Layer.L1, Layer.L2)
    error = LayerFailure(kind, "none", {"kind": "unknown"}, datetime.now(UTC))
    calls = dispatch(
        monkeypatch, {"L1": [error, FailureClass.CHALLENGE], "L2": [error]}
    )
    with pytest.raises(RunnerFailure) as caught:
        await run_ladder(source, source.request.profile, source.run_context.deadline)
    assert [key for key, _ in calls] == ["L1", "L1", "L2"]
    assert len(caught.value.failures) == 3


async def test_local_runtime_failure_is_not_hidden_by_next_layer(source, monkeypatch):
    source = layers(source, Layer.L1, Layer.L2)
    calls = dispatch(
        monkeypatch, {"L1": [FailureClass.RUNTIME_UNAVAILABLE] * 2, "L2": [None]}
    )
    with pytest.raises(RunnerFailure):
        await run_ladder(source, source.request.profile, source.run_context.deadline)
    assert [key for key, _ in calls] == ["L1", "L1"]


@pytest.mark.parametrize("seconds", [None, 60, 0.01])
async def test_retry_after_must_fit_remaining_budget(source, monkeypatch, seconds):
    source = layers(source, Layer.L1)
    now = datetime.now(UTC)
    retry_at = None if seconds is None else now + timedelta(seconds=seconds)
    error = LayerFailure(
        FailureClass.RATE_LIMITED,
        "①",
        {"kind": "upstream_response", "http_status": 429},
        retry_at,
    )
    calls = dispatch(monkeypatch, {"L1": [error, None]})
    if seconds == 0.01:
        result = await run_ladder(
            source, source.request.profile, source.run_context.deadline
        )
        assert datetime.now(UTC) >= retry_at
        assert len(calls) == 2 and result.failures[0].retry_after == retry_at
    else:
        with pytest.raises(RunnerFailure) as caught:
            await run_ladder(
                source, source.request.profile, source.run_context.deadline
            )
        assert len(calls) == 1 and caught.value.failure.retry_after == retry_at


@pytest.mark.parametrize(
    "code", ["cancelled", "inspection_timeout", "download_timeout"]
)
async def test_termination_signals_never_retry(source, monkeypatch, code):
    calls = dispatch(monkeypatch, {"L1": [RunnerFailure(code)]})
    with pytest.raises(RunnerFailure):
        await run_ladder(source, source.request.profile, source.run_context.deadline)
    assert len(calls) == 1


@pytest.fixture
def identity_material(tmp_path, monkeypatch):
    root = tmp_path / "identity"
    root.mkdir(mode=0o700)
    operation = root / "operation"
    operation.mkdir(mode=0o700)
    cookie = operation / "cookies.txt"
    cookie.touch(mode=0o600)
    monkeypatch.setattr(identity, "COOKIE_TMPFS_ROOT", root)
    monkeypatch.setattr(identity, "_on_tmpfs", lambda path: True)
    return IdentityMaterial(cookie, "stable-digest")


@pytest.mark.parametrize("policy", list(ProviderIdentity))
async def test_identity_injection_policy(
    source, monkeypatch, identity_material, policy
):
    source = layers(source, Layer.L1, identity=policy)
    fetched = []

    async def fetch(site, task_id, deadline):
        fetched.append((site, task_id, deadline))
        return identity_material

    monkeypatch.setattr(identity, "fetch_identity", fetch)
    script = (
        [None]
        if policy is not ProviderIdentity.NONE
        else [FailureClass.LOGIN_REQUIRED, None]
    )
    calls = dispatch(monkeypatch, {"L1": script})
    if policy is ProviderIdentity.NONE:
        with pytest.raises(RunnerFailure, match="login required"):
            await run_ladder(
                source, source.request.profile, source.run_context.deadline
            )
        assert not fetched
    else:
        result = await run_ladder(
            source, source.request.profile, source.run_context.deadline
        )
        assert len(fetched) == 1 and fetched[0] == (
            "bilibili",
            "engine_sample",
            source.run_context.deadline,
        )
        assert result.execution_context.identity_used
        assert result.execution_context.identity_digest == "stable-digest"
        assert calls[-1][1] == identity_material
        assert calls[0][1] is identity_material and len(calls) == 1
        await close_material(result.run_context)
        assert not identity_material.cookie_file.exists()


async def test_prefer_login_failure_does_not_fetch_or_retry_again(
    source, monkeypatch, identity_material
):
    source = layers(source, Layer.L1, Layer.L2, identity=ProviderIdentity.PREFER)

    async def fetch(*args):
        return identity_material

    monkeypatch.setattr(identity, "fetch_identity", fetch)
    calls = dispatch(
        monkeypatch, {"L1": [FailureClass.LOGIN_REQUIRED] * 2, "L2": [None]}
    )
    with pytest.raises(RunnerFailure, match="login required"):
        await run_ladder(source, source.request.profile, source.run_context.deadline)
    assert len(calls) == 1 and not identity_material.cookie_file.exists()


async def test_required_stub_fails_before_platform_io(source, monkeypatch):
    source = layers(source, Layer.L1, identity=ProviderIdentity.REQUIRED)
    calls = dispatch(monkeypatch, {"L1": [None]})
    with pytest.raises(RunnerFailure, match="identity unavailable"):
        await run_ladder(source, source.request.profile, source.run_context.deadline)
    assert not calls


@pytest.mark.parametrize("phase", ["identity", "layer", "retry_after"])
async def test_shared_timeout_cleans_material_before_return(source, monkeypatch, phase):
    browser = Browser()
    deadline = datetime.now(UTC) + timedelta(seconds=0.04)
    source = replace(
        source,
        run_context=replace(source.run_context, deadline=deadline, browser=browser),
    )
    source = layers(
        source,
        Layer.L1,
        identity=ProviderIdentity.REQUIRED
        if phase == "identity"
        else ProviderIdentity.NONE,
    )
    entered = asyncio.Event()

    async def blocking(*args):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(identity, "fetch_identity", blocking)

    class Blocked:
        async def resolve(self, source, ctx):
            await blocking()

    monkeypatch.setitem(LAYER_TABLE, Layer.L1, Blocked)
    with pytest.raises(RunnerFailure, match="inspection timeout"):
        await run_ladder(source, source.request.profile, deadline)
    assert entered.is_set() and browser.events == [("close", None)]


@pytest.mark.parametrize("phase", ["layer", "retry_after"])
async def test_cancel_waits_for_browser_cleanup(source, monkeypatch, phase):
    browser = Browser()
    source = replace(source, run_context=replace(source.run_context, browser=browser))
    entered = asyncio.Event()

    class Waiting:
        async def resolve(self, source, ctx):
            entered.set()
            if phase == "retry_after":
                raise LayerFailure(
                    FailureClass.RATE_LIMITED,
                    "①",
                    {"kind": "unknown"},
                    datetime.now(UTC) + timedelta(seconds=1),
                )
            await asyncio.Event().wait()

    monkeypatch.setitem(LAYER_TABLE, Layer.L1, Waiting)
    task = asyncio.create_task(
        run_ladder(source, source.request.profile, source.run_context.deadline)
    )
    await entered.wait()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert browser.events == [("close", None)]


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider_key", "youtube"),
        ("registry_revision", "rotated"),
        ("engine_revision", "rotated"),
        ("egress_route", "rotated"),
        ("egress_revision", "rotated"),
        ("egress_class", "datacenter"),
        ("egress_observed_ip", "203.0.113.1"),
        ("resolved_layer", "L3"),
    ],
)
async def test_download_binding_change_rejected_before_io(
    source, monkeypatch, field, value
):
    expected = replace(source.execution_context, **{field: value})
    source = replace(source, expected_context=expected)
    calls = dispatch(monkeypatch, {"L1": [None]})
    with pytest.raises(RunnerFailure, match="context changed"):
        await run_ladder(source, source.request.profile, source.run_context.deadline)
    assert not calls


async def test_download_refreshes_identity_and_checks_digest_before_io(
    source, monkeypatch, identity_material
):
    source = replace(
        source,
        expected_context=replace(
            source.execution_context, identity_used=True, identity_digest="old"
        ),
    )

    async def fetch(*args):
        return identity_material

    monkeypatch.setattr(identity, "fetch_identity", fetch)
    calls = dispatch(monkeypatch, {"L1": [None]})
    with pytest.raises(RunnerFailure, match="context changed"):
        await run_ladder(source, source.request.profile, source.run_context.deadline)
    assert not calls and not identity_material.cookie_file.exists()


async def test_download_client_change_never_silently_reconfirmed(source, monkeypatch):
    source = replace(source, expected_context=source.execution_context)
    dispatch(
        monkeypatch, {"L1": [None]}, after=lambda ctx: resolved(ctx, client="changed")
    )
    with pytest.raises(RunnerFailure, match="context changed"):
        await run_ladder(source, source.request.profile, source.run_context.deadline)


@pytest.mark.parametrize("download", [False, True])
async def test_parse_is_capped_but_download_reparse_uses_download_budget(
    source, monkeypatch, download
):
    deadline = datetime.now(UTC) + timedelta(seconds=300)
    source = replace(
        source,
        run_context=replace(source.run_context, deadline=deadline),
        expected_context=source.execution_context if download else None,
    )
    dispatch(monkeypatch, {"L1": [None]})
    durations = []
    original = asyncio.timeout

    def timeout(duration):
        durations.append(duration)
        return original(duration)

    monkeypatch.setattr("app.workers.runner.engine.ladder.asyncio.timeout", timeout)
    await run_ladder(source, source.request.profile, deadline)
    assert len(durations) == 1
    assert durations[0] > 120 if download else durations[0] <= 120


async def test_expired_required_identity_does_not_call_source(source, monkeypatch):
    source = layers(source, Layer.L1, identity=ProviderIdentity.REQUIRED)

    async def unexpected(*args):
        pytest.fail("expired deadline started identity IO")

    monkeypatch.setattr(identity, "fetch_identity", unexpected)
    with pytest.raises(RunnerFailure, match="inspection timeout"):
        await run_ladder(source, source.request.profile, datetime.now(UTC))


@pytest.mark.parametrize(
    "cause",
    [
        "extension_disconnected",
        "extension_timeout",
        "credential_missing",
        "identity_cookie_rules_unverified",
    ],
)
@pytest.mark.parametrize("terminal", [False, True])
async def test_prefer_unavailable_is_anonymous_with_failure_evidence(
    source, monkeypatch, cause, terminal, caplog
):
    from unittest.mock import AsyncMock

    source = layers(source, Layer.L1, identity=ProviderIdentity.PREFER)
    fetch = AsyncMock(side_effect=identity._unavailable(cause))
    monkeypatch.setattr(identity, "fetch_identity", fetch)
    calls = dispatch(
        monkeypatch, {"L1": [FailureClass.LOGIN_REQUIRED if terminal else None]}
    )
    if terminal:
        with pytest.raises(RunnerFailure, match="login required") as caught:
            await run_ladder(
                source, source.request.profile, source.run_context.deadline
            )
        history = caught.value.failures
    else:
        result = await run_ladder(
            source, source.request.profile, source.run_context.deadline
        )
        assert result.execution_context.identity_used is False
        assert result.execution_context.identity_digest is None
        history = result.failures
    assert len(calls) == 1 and calls[0][1] is None
    fetch.assert_awaited_once()
    assert history[0].failure_class is FailureClass.IDENTITY_UNAVAILABLE
    assert history[0].evidence["cause_code"] == cause
    assert history[0].layer == "L1" and history[0].gate == "③"
    assert any(
        "class=identity_unavailable" in record.message
        and f"'cause_code': '{cause}'" in record.message
        for record in caplog.records
    )


@pytest.mark.parametrize("policy", [ProviderIdentity.PREFER, ProviderIdentity.REQUIRED])
async def test_download_lost_identity_returns_context_changed_before_io(
    source, monkeypatch, policy
):
    from unittest.mock import AsyncMock

    source = layers(source, Layer.L1, identity=policy)
    source = replace(
        source,
        expected_context=replace(
            source.execution_context, identity_used=True, identity_digest="old"
        ),
    )
    fetch = AsyncMock(side_effect=identity._unavailable("extension_disconnected"))
    monkeypatch.setattr(identity, "fetch_identity", fetch)
    calls = dispatch(monkeypatch, {"L1": [None]})
    with pytest.raises(RunnerFailure, match="context changed") as caught:
        await run_ladder(source, source.request.profile, source.run_context.deadline)
    assert not calls and caught.value.status == 409
    assert caught.value.failure.evidence["cause_code"] == "extension_disconnected"
    assert caught.value.failure.stage == "download"
    assert caught.value.failures[0].failure_class is FailureClass.IDENTITY_UNAVAILABLE
    fetch.assert_awaited_once()


async def test_anonymous_download_stays_anonymous_even_if_identity_appears(
    source, monkeypatch
):
    from unittest.mock import AsyncMock

    source = layers(source, Layer.L1, identity=ProviderIdentity.PREFER)
    source = replace(source, expected_context=source.execution_context)
    fetch = AsyncMock(side_effect=AssertionError("anonymous download fetched identity"))
    monkeypatch.setattr(identity, "fetch_identity", fetch)
    calls = dispatch(monkeypatch, {"L1": [None]})
    result = await run_ladder(
        source, source.request.profile, source.run_context.deadline
    )
    assert result.execution_context == source.expected_context
    assert calls == [("L1", None)]
    fetch.assert_not_awaited()
