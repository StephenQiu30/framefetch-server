"""Wire contracts for the Runner → broker channel.

Cookie material never crosses it in clear text: every jar is a sealed box
(``sealing.py``) addressed to the receiver's key.
"""

from __future__ import annotations

from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

STATUS_PATH: Final = "/internal/v1/site-sessions/status"
LEASE_PATH: Final = "/internal/v1/site-sessions/lease"

Site = Annotated[str, StringConstraints(pattern=r"^[a-z0-9.-]{3,253}$")]
TaskId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
Encoded = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+$", max_length=3_000_000)
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# Runner → broker ------------------------------------------------------------


class StatusRequest(_Strict):
    site: Site


class StatusResponse(_Strict):
    site: Site
    seed_revision: int = Field(ge=1)


class LeaseRequest(_Strict):
    task_id: TaskId
    site: Site
    seed_revision: int = Field(ge=1)
    public_key: Encoded


class LeaseResponse(_Strict):
    site: Site
    seed_revision: int = Field(ge=1)
    expires_at: int
    jar: Encoded
    headers: Encoded | None = None


def lease_associated_data(
    kind: str, task_id: str, site: str, seed_revision: int, expires_at: int
) -> bytes:
    fields = (kind, task_id, site, seed_revision, expires_at)
    return ("site-session-lease:v1:" + ":".join(map(str, fields))).encode()
