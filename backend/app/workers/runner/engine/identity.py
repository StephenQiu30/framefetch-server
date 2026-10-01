"""Runner-only identity material. P0 never reads host account state."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.services.provider_failures import FailureClass
from app.workers.runner.engine.layers.base import LayerFailure


@dataclass(frozen=True, slots=True)
class IdentityMaterial:
    cookie_file: Path = field(repr=False)
    digest: str


async def fetch_identity(
    site: str, task_id: str, deadline: datetime
) -> IdentityMaterial:
    raise LayerFailure(
        FailureClass.IDENTITY_UNAVAILABLE,
        "③",
        {"kind": "runtime", "cause_code": "identity_not_implemented"},
    )
