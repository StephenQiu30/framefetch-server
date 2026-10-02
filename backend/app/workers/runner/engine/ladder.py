"""Bounded layer execution and task-scoped recovery from Design 17 §3.5."""

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.services.provider_failures import FailureClass, ProviderFailure
from app.services.provider_types import Layer, ProviderIdentity
from app.workers.runner.engine import identity
from app.workers.runner.engine.layers.base import Layer as ResolverLayer
from app.workers.runner.engine.layers.base import LayerFailure
from app.workers.runner.engine.layers.browser import BrowserLayer
from app.workers.runner.engine.layers.http import HttpLayer
from app.workers.runner.engine.layers.prepared import PreparedLayer
from app.workers.runner.engine.resolved import Resolution
from app.workers.runner.engine.run_context import ResolutionSource, RunContext
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import ProviderProfile

_LOG = logging.getLogger(__name__)

LAYER_TABLE: dict[Layer, type[ResolverLayer]] = {
    Layer.L1: HttpLayer,
    Layer.L2: PreparedLayer,
    Layer.L3: BrowserLayer,
}
_NEXT_LAYER = {
    FailureClass.NETWORK_BLOCKED,
    FailureClass.CHALLENGE,
    FailureClass.EXTRACTOR_BROKEN,
    FailureClass.FORMAT_UNAVAILABLE,
}
_CONTEXT_BINDING = (
    "provider_key",
    "registry_revision",
    "engine_revision",
    "egress_route",
    "egress_revision",
    "egress_class",
    "egress_observed_ip",
)


def log_failure(source: ResolutionSource, failure: ProviderFailure) -> None:
    _LOG.warning(
        "resolver failed task=%s provider=%s layer=%s "
        "stage=%s class=%s gate=%s evidence=%s",
        source.workspace.path.name.rsplit("-", 1)[0],
        source.request.profile.key,
        failure.layer,
        failure.stage,
        failure.failure_class,
        failure.gate,
        failure.evidence,
    )


async def close_material(ctx: RunContext) -> None:
    try:
        if ctx.browser is not None:
            cleanup = asyncio.create_task(ctx.browser.close())
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise
    finally:
        # Only files validated on the operation-private tmpfs can be removed.
        if ctx.cookie_file is not None and ctx.cookie_file.exists():
            identity.validate_cookie_file(ctx.cookie_file)
            ctx.cookie_file.unlink()
            try:
                ctx.cookie_file.parent.rmdir()
            except OSError:
                pass  # Other files are owned by the identity implementation.


async def run_ladder(
    source: ResolutionSource, profile: ProviderProfile, deadline: datetime
) -> Resolution:
    context = source.execution_context
    expected = source.expected_context
    # Never extend an already assigned budget. Downloads use their own deadline.
    deadline = min(deadline, source.run_context.deadline)
    if expected is None:
        deadline = min(deadline, datetime.now(UTC) + timedelta(seconds=120))
    ctx = replace(source.run_context, deadline=deadline)
    failures: list[ProviderFailure] = []
    task_retries: set[FailureClass] = set()
    transferred = False
    active_layer: ResolverLayer | None = None

    async def inject_identity() -> None:
        nonlocal ctx
        material = await identity.fetch_identity(
            profile.key, source.workspace.path.name.rsplit("-", 1)[0], deadline
        )
        ctx = ctx.with_material(identity=material)

    try:
        remaining = (deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise RunnerFailure(
                "download_timeout" if expected is not None else "inspection_timeout",
                status=504,
            )
        async with asyncio.timeout(remaining):
            if profile != source.request.profile:
                raise RunnerFailure("context_changed", status=409)
            layers = profile.ladder
            if expected is not None:
                binding = replace(
                    context,
                    egress_route=ctx.egress.route,
                    egress_revision=ctx.egress.revision,
                    egress_class=ctx.egress.egress_class,
                    egress_observed_ip=ctx.egress.observed_ip,
                )
                if expected.resolved_layer not in layers or any(
                    getattr(expected, name) != getattr(binding, name)
                    for name in _CONTEXT_BINDING
                ):
                    raise RunnerFailure("context_changed", status=409)
                layers = (Layer(expected.resolved_layer),)
            if profile.identity is ProviderIdentity.NONE:
                if ctx.identity is not None or (expected and expected.identity_used):
                    raise RunnerFailure("context_changed", status=409)
            if (
                layers == (Layer.L3,)
                and LAYER_TABLE[Layer.L3] is BrowserLayer
                and not BrowserLayer.has_parser(profile.key)
            ):
                context = replace(
                    context, resolved_layer=Layer.L3, client=f"{profile.key}:browser"
                )
                raise LayerFailure(
                    FailureClass.RUNTIME_UNAVAILABLE,
                    "none",
                    {"kind": "runtime", "cause_code": "browser_parser_missing"},
                )
            if profile.identity is ProviderIdentity.REQUIRED or (
                profile.identity is ProviderIdentity.PREFER
                and (expected is None or expected.identity_used)
            ):
                try:
                    await inject_identity()
                except RunnerFailure as error:
                    if (
                        error.failure.failure_class
                        is not FailureClass.IDENTITY_UNAVAILABLE
                    ):
                        raise
                    error.attributed_to(replace(context, resolved_layer=layers[0]))
                    if expected is not None and expected.identity_used:
                        failures.append(replace(error.failure, stage="download"))
                        raise RunnerFailure(
                            "context_changed",
                            status=409,
                            stage="download",
                            evidence=error.failure.evidence,
                            evidence_kind=error.failure.evidence_kind,
                        ) from error
                    if profile.identity is ProviderIdentity.REQUIRED:
                        raise
                    # Prefer falls back only at initial resolve, keeping the safe
                    # cause in failure history even when anonymous IO succeeds.
                    failures.append(error.failure)
                    log_failure(source, error.failure)
                    ctx = replace(ctx, identity=None, cookie_file=None)
            if expected is not None and (
                expected.identity_used != (ctx.identity is not None)
                or expected.identity_digest
                != (ctx.identity.digest if ctx.identity else None)
            ):
                raise RunnerFailure("context_changed", status=409)
            for layer_key in layers:
                layer = LAYER_TABLE[layer_key]()
                active_layer = layer
                layer_retried = False
                while True:
                    context = replace(
                        context,
                        resolved_layer=layer_key,
                        client=f"{profile.key}:browser"
                        if layer_key is Layer.L3
                        else profile.client_profile,
                        identity_used=ctx.identity is not None,
                        identity_digest=ctx.identity.digest if ctx.identity else None,
                    )
                    try:
                        media = await layer.resolve(
                            replace(source, execution_context=context), ctx
                        )
                        # Prepared clients retain safe attempt facts within the layer.
                        failures.extend(getattr(layer, "failures", ()))
                        ctx = media.run_context or ctx
                        context = replace(
                            context,
                            client=media.client,
                            egress_route=ctx.egress.route,
                            egress_revision=ctx.egress.revision,
                            egress_class=ctx.egress.egress_class,
                            egress_observed_ip=ctx.egress.observed_ip,
                            identity_used=ctx.identity is not None,
                            identity_digest=ctx.identity.digest
                            if ctx.identity
                            else None,
                            browser_context_kind=(
                                "authenticated" if ctx.identity else "anonymous"
                            )
                            if ctx.browser
                            else "none",
                        )
                        if expected is not None and expected != context:
                            raise RunnerFailure("context_changed", status=409)
                        transferred = True
                        return Resolution(media, context, tuple(failures), ctx)
                    except RunnerFailure as error:
                        error.attributed_to(context)
                        attempt_failures = error.failures or (error.failure,)
                        failures.extend(attempt_failures)
                        for failure in attempt_failures:
                            log_failure(source, failure)
                        kind = error.failure.failure_class
                        if kind in _NEXT_LAYER and layer_key != layers[-1]:
                            break
                        if kind is FailureClass.TRANSIENT:
                            # Cancellation/deadline outcomes are never recoverable.
                            if layer_retried or error.code in {
                                "cancelled",
                                "inspection_timeout",
                                "download_timeout",
                            }:
                                raise
                            layer_retried = True
                            await asyncio.sleep(0)
                            continue
                        if (
                            kind
                            not in {
                                FailureClass.RATE_LIMITED,
                                FailureClass.RUNTIME_UNAVAILABLE,
                            }
                            or kind in task_retries
                        ):
                            raise
                        delay = 0.0
                        if kind is FailureClass.RATE_LIMITED:
                            if error.failure.retry_after is None:
                                raise
                            delay = max(
                                0.0,
                                (
                                    error.failure.retry_after - datetime.now(UTC)
                                ).total_seconds(),
                            )
                        if delay >= (deadline - datetime.now(UTC)).total_seconds():
                            raise
                        task_retries.add(kind)
                        await asyncio.sleep(delay)
            raise RunnerFailure("format_unavailable", status=409)
    except TimeoutError as exc:
        active_client = getattr(active_layer, "active_client", None)
        if active_client is not None:
            context = replace(context, client=active_client)
        timeout_error = RunnerFailure(
            "download_timeout" if expected is not None else "inspection_timeout",
            status=504,
        ).attributed_to(
            replace(
                context,
                identity_used=ctx.identity is not None,
                identity_digest=ctx.identity.digest if ctx.identity else None,
            )
        )
        timeout_error.failures = (*failures, timeout_error.failure)
        raise timeout_error from exc
    except RunnerFailure as error:
        error.attributed_to(
            replace(
                context,
                identity_used=ctx.identity is not None,
                identity_digest=ctx.identity.digest if ctx.identity else None,
            )
        )
        if not failures or failures[-1] != error.failure:
            failures.append(error.failure)
        error.failure = replace(
            error.failure,
            summary=(
                f"Stopped at {context.resolved_layer}: "
                f"{error.failure.failure_class.value}; "
                f"{error.failure.evidence.get('cause_code') or error.code}"
            ),
        )
        error.failures = tuple(failures)
        raise
    finally:
        # A successful result transfers material ownership to the caller.
        if not transferred:
            await close_material(ctx)
