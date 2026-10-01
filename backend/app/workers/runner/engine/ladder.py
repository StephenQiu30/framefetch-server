"""Declared layer dispatch; complete transition policy belongs to R2."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

from app.services.provider_failures import FailureClass, ProviderFailure
from app.services.provider_types import Layer, ProviderIdentity
from app.workers.runner.engine.layers.base import Layer as ResolverLayer
from app.workers.runner.engine.layers.browser import BrowserLayer
from app.workers.runner.engine.layers.http import HttpLayer
from app.workers.runner.engine.layers.prepared import PreparedLayer
from app.workers.runner.engine.resolved import Resolution
from app.workers.runner.engine.run_context import ResolutionSource, RunContext
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import ProviderProfile

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


async def close_material(ctx: RunContext) -> None:
    if ctx.browser is not None:
        cleanup = asyncio.create_task(ctx.browser.close())
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await cleanup
            raise


async def run_ladder(
    source: ResolutionSource, profile: ProviderProfile, deadline: datetime
) -> Resolution:
    context = source.execution_context
    expected = source.expected_context
    ctx = replace(source.run_context, deadline=deadline)
    failures: list[ProviderFailure] = []
    try:
        if profile != source.request.profile:
            raise RunnerFailure("context_changed", status=409).attributed_to(context)
        layers = profile.ladder
        if expected is not None:
            if expected.resolved_layer not in layers:
                raise RunnerFailure("context_changed", status=409).attributed_to(
                    expected
                )
            layers = (Layer(expected.resolved_layer),)
        if profile.identity is ProviderIdentity.REQUIRED and ctx.identity is None:
            raise RunnerFailure("login_required", status=422).attributed_to(context)
        if expected is not None and (
            expected.identity_used != (ctx.identity is not None)
            or expected.identity_digest
            != (ctx.identity.digest if ctx.identity else None)
        ):
            raise RunnerFailure("context_changed", status=409).attributed_to(expected)
        for layer_key in layers:
            layer = LAYER_TABLE[layer_key]()
            retried: set[FailureClass] = set()
            while True:
                remaining = (deadline - datetime.now(UTC)).total_seconds()
                if remaining <= 0:
                    raise RunnerFailure("inspection_timeout", status=504).attributed_to(
                        context
                    )
                context = replace(context, resolved_layer=layer_key)
                try:
                    async with asyncio.timeout(remaining):
                        media = await layer.resolve(
                            replace(source, execution_context=context), ctx
                        )
                    actual_ctx = media.run_context or ctx
                    ctx = actual_ctx
                    context = replace(
                        context,
                        client=media.client,
                        egress_route=actual_ctx.egress.route,
                        egress_revision=actual_ctx.egress.revision,
                        egress_class=actual_ctx.egress.egress_class,
                        egress_observed_ip=actual_ctx.egress.observed_ip,
                        identity_used=actual_ctx.identity is not None,
                        identity_digest=actual_ctx.identity.digest
                        if actual_ctx.identity
                        else None,
                        browser_context_kind=(
                            "authenticated" if actual_ctx.identity else "anonymous"
                        )
                        if actual_ctx.browser
                        else "none",
                    )
                    if expected is not None and expected != context:
                        raise RunnerFailure(
                            "context_changed", status=409
                        ).attributed_to(context)
                    return Resolution(media, context, tuple(failures), ctx)
                except RunnerFailure as error:
                    error.attributed_to(context)
                    failures.append(error.failure)
                    kind = error.failure.failure_class
                    if kind in _NEXT_LAYER and layer_key != layers[-1]:
                        break
                    if kind in retried or kind not in {
                        FailureClass.TRANSIENT,
                        FailureClass.RUNTIME_UNAVAILABLE,
                        FailureClass.RATE_LIMITED,
                    }:
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
                    retried.add(kind)
                    await asyncio.sleep(delay)
        raise RunnerFailure("format_unavailable", status=409).attributed_to(context)
    except BaseException:
        await close_material(ctx)
        raise
