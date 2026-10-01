"""L2 placeholder; P0 never enables proof preparation."""

from app.services.provider_failures import FailureClass
from app.workers.runner.engine.layers.base import LayerFailure
from app.workers.runner.engine.resolved import ResolvedMedia
from app.workers.runner.engine.run_context import ResolutionSource, RunContext


class PreparedLayer:
    async def resolve(self, source: ResolutionSource, ctx: RunContext) -> ResolvedMedia:
        raise LayerFailure(
            FailureClass.RUNTIME_UNAVAILABLE,
            "②",
            {"kind": "runtime", "cause_code": "preparation_not_implemented"},
        )
