"""L1: yt-dlp extraction, content checks and bounded probing."""

from dataclasses import fields, replace

from app.workers.runner.engine.layers.base import LayerFailure
from app.workers.runner.engine.resolved import ResolvedMedia
from app.workers.runner.engine.run_context import ResolutionSource, RunContext
from app.workers.runner.errors import RunnerFailure


class HttpLayer:
    async def resolve(self, source: ResolutionSource, ctx: RunContext) -> ResolvedMedia:
        client = (
            source.request.profile.client_profile
            if source.execution_context.resolved_layer == "L1"
            else source.execution_context.client
        )
        source = replace(
            source, execution_context=replace(source.execution_context, client=client)
        )
        try:
            media = (
                await source.pipeline.with_context(ctx)
                .with_client(source.execution_context.client)
                .inspect(
                    source.request,
                    source.workspace,
                    context=source.execution_context,
                    cookie_jar=ctx.cookie_file,
                )
            )
        except RunnerFailure as error:
            raise LayerFailure.from_runner_failure(
                error.attributed_to(source.execution_context)
            ) from error
        return ResolvedMedia(
            **{item.name: getattr(media, item.name) for item in fields(media)},
            client=source.execution_context.client,
            handoff="http",
        )
