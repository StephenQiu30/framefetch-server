"""WPC obtains browser PO Tokens; yt-dlp retains extraction and HTTP handoff."""

from dataclasses import replace

from app.services.provider_types import BrowserRules
from app.workers.runner.engine.layers.http import HttpLayer
from app.workers.runner.engine.resolved import ResolvedMedia
from app.workers.runner.engine.run_context import ResolutionSource, RunContext
from app.workers.runner.errors import RunnerFailure

RULES = BrowserRules("youtube")
CLIENT = "youtube:wpc:mweb"


async def resolve(source: ResolutionSource, ctx: RunContext) -> ResolvedMedia:
    if source.expected_context is not None and source.expected_context.client != CLIENT:
        raise RunnerFailure("context_changed", status=409)
    context = replace(source.execution_context, client=CLIENT)
    return await HttpLayer().resolve(replace(source, execution_context=context), ctx)
