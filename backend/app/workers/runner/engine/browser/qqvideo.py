"""qqvideo response rules and parser placeholder for R3/R6."""

from collections.abc import Mapping

from app.services.provider_failures import FailureClass
from app.services.provider_types import BrowserRules
from app.workers.runner.engine.layers.base import LayerFailure
from app.workers.runner.engine.resolved import ResolvedMedia

RULES = BrowserRules("qqvideo")


def parse_response(payload: Mapping[str, object]) -> ResolvedMedia:
    raise LayerFailure(
        FailureClass.RUNTIME_UNAVAILABLE,
        "②",
        {"kind": "runtime", "cause_code": "browser_parser_not_implemented"},
    )
