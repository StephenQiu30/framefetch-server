"""L1: preserve R0's yt-dlp, entitlement and bounded probing pipeline."""

from dataclasses import fields

from app.workers.runner.engine.layers.base import LayerFailure
from app.workers.runner.engine.resolved import ResolvedMedia
from app.workers.runner.engine.run_context import ResolutionSource, RunContext
from app.workers.runner.errors import RunnerFailure


class HttpLayer:
    async def resolve(self, source: ResolutionSource, ctx: RunContext) -> ResolvedMedia:
        try:
            media = await source.pipeline.inspect(
                source.request,
                source.workspace,
                context=source.execution_context,
                cookie_jar=ctx.cookie_file,
            )
        except RunnerFailure as error:
            raise LayerFailure.from_runner_failure(error) from error
        return ResolvedMedia(
            **{item.name: getattr(media, item.name) for item in fields(media)},
            client=source.execution_context.client,
            handoff="http",
        )
