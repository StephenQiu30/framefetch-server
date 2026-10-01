"""P0 executes only anonymous L1, retaining R0's retries and deadline."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

from app.services.provider_failures import FailureClass, ProviderFailure
from app.services.provider_types import ProviderIdentity
from app.workers.runner.engine.layers.http import HttpLayer
from app.workers.runner.engine.resolved import Resolution
from app.workers.runner.engine.run_context import ResolutionSource
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import ProviderProfile


async def run_ladder(
    source: ResolutionSource, profile: ProviderProfile, deadline: datetime
) -> Resolution:
    context = source.execution_context
    if profile != source.request.profile or context.resolved_layer != "L1":
        raise RunnerFailure("context_changed", status=409).attributed_to(context)
    if profile.identity is ProviderIdentity.REQUIRED:
        raise RunnerFailure("login_required", status=422).attributed_to(context)
    ctx = replace(source.run_context, deadline=deadline)
    if (
        ctx.cookie_file is not None
        or ctx.identity is not None
        or ctx.browser is not None
    ):
        raise RunnerFailure("context_changed", status=409).attributed_to(context)
    failures: list[ProviderFailure] = []
    retried: set[FailureClass] = set()
    layer = HttpLayer()
    while True:
        remaining = (deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise RunnerFailure("inspection_timeout", status=504).attributed_to(context)
        try:
            async with asyncio.timeout(remaining):
                media = await layer.resolve(source, ctx)
            return Resolution(media, context, tuple(failures))
        except RunnerFailure as error:
            failures.append(error.failure)
            kind = error.failure.failure_class
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
                    0.0, (error.failure.retry_after - datetime.now(UTC)).total_seconds()
                )
            if delay >= (deadline - datetime.now(UTC)).total_seconds():
                raise
            retried.add(kind)
            await asyncio.sleep(delay)
