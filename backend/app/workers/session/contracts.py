"""Wire contracts for the Runner → broker and broker → browser channels.

Cookie material never crosses either channel in clear text: every jar or header
set is a sealed box (``sealing.py``) addressed to the receiver's key.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

STATUS_PATH: Final = "/internal/v1/site-sessions/status"
LEASE_PATH: Final = "/internal/v1/site-sessions/lease"
FAILURE_PATH: Final = "/internal/v1/site-sessions/failures"
BROWSER_IDENTITY_PATH: Final = "/v1/identity"
BROWSER_BOOTSTRAP_PATH: Final = "/v1/sites/bootstrap"
BROWSER_KEEPALIVE_PATH: Final = "/v1/sites/keepalive"
BROWSER_HEADERS_PATH: Final = "/v1/sites/headers"
BROWSER_FORGET_PATH: Final = "/v1/sites/forget"

Site = Annotated[str, StringConstraints(pattern=r"^[a-z0-9.-]{3,253}$")]
TaskId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
Encoded = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+$", max_length=3_000_000)
]
ErrorCode = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,64}$")]


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
    jar_version: int = Field(ge=0)
    expires_at: int
    jar: Encoded
    headers: Encoded | None = None


class FailureReport(_Strict):
    site: Site
    seed_revision: int = Field(ge=1)
    error_code: ErrorCode


def lease_associated_data(
    kind: str, task_id: str, site: str, seed_revision: int, expires_at: int
) -> bytes:
    fields = (kind, task_id, site, seed_revision, expires_at)
    return ("site-session-lease:v1:" + ":".join(map(str, fields))).encode()


# Broker → browser -----------------------------------------------------------


class BrowserOutcome(StrEnum):
    VERIFIED = "verified"
    LOGGED_OUT = "logged_out"
    AUTH_FAILURE = "auth_failure"
    PROFILE_MISSING = "profile_missing"
    UNAVAILABLE = "unavailable"


class IdentityRequest(_Strict):
    pass


class BrowserIdentity(_Strict):
    public_key: Encoded


class BootstrapRequest(_Strict):
    site: Site
    seed_revision: int = Field(ge=1)
    jar: Encoded
    reply_key: Encoded


class KeepaliveRequest(_Strict):
    site: Site
    seed_revision: int = Field(ge=1)
    reply_key: Encoded


class BrowserResult(_Strict):
    outcome: BrowserOutcome
    error_code: ErrorCode | None = None
    jar: Encoded | None = None


class HeadersRequest(_Strict):
    site: Site
    seed_revision: int = Field(ge=1)
    task_id: TaskId
    expires_at: int
    public_key: Encoded


class HeadersResponse(_Strict):
    headers: Encoded


class ForgetRequest(_Strict):
    site: Site


def bootstrap_associated_data(site: str, seed_revision: int) -> bytes:
    return f"site-session-bootstrap:v1:{site}:{seed_revision}".encode()


def export_associated_data(site: str, seed_revision: int) -> bytes:
    return f"site-session-export:v1:{site}:{seed_revision}".encode()
