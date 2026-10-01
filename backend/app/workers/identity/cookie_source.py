"""Host service placeholder: no server, Profile or Keychain access before R4."""

from datetime import datetime

from app.services.provider_failures import FailureClass
from app.workers.runner.engine.identity import IdentityMaterial
from app.workers.runner.engine.layers.base import LayerFailure


async def fetch_identity(
    site: str, task_id: str, deadline: datetime
) -> IdentityMaterial:
    raise LayerFailure(
        FailureClass.IDENTITY_UNAVAILABLE,
        "③",
        {"kind": "runtime", "cause_code": "cookie_source_not_implemented"},
    )
