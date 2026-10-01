"""L3 placeholder; existing browser_runtime remains disabled in P0's ladder."""

from app.services.provider_failures import FailureClass
from app.workers.runner.engine.layers.base import LayerFailure
from app.workers.runner.engine.resolved import ResolvedMedia
from app.workers.runner.engine.run_context import ResolutionSource, RunContext


class BrowserLayer:
    async def resolve(self, source: ResolutionSource, ctx: RunContext) -> ResolvedMedia:
        raise LayerFailure(
            FailureClass.RUNTIME_UNAVAILABLE,
            "none",
            {"kind": "runtime", "cause_code": "browser_not_implemented"},
        )
