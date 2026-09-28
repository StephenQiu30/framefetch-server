"""Wire contracts for the Runner → broker and broker → browser channels.

Cookie material never crosses either channel in clear text: every jar or header
set is a sealed box (``sealing.py``) addressed to the receiver's key.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

STATUS_PATH: Final = "/internal/v1/site-sessions/status"
LEASE_PATH: Final = "/internal/v1/site-sessions/lease"
FAILURE_PATH: Final = "/internal/v1/site-sessions/failures"
ADMIN_LOGIN_START_PATH: Final = "/internal/v1/site-sessions/logins/start"
ADMIN_LOGIN_FRAME_PATH: Final = "/internal/v1/site-sessions/logins/frame"
ADMIN_LOGIN_INPUT_PATH: Final = "/internal/v1/site-sessions/logins/input"
ADMIN_LOGIN_FINISH_PATH: Final = "/internal/v1/site-sessions/logins/finish"
ADMIN_LOGIN_CANCEL_PATH: Final = "/internal/v1/site-sessions/logins/cancel"
BROWSER_IDENTITY_PATH: Final = "/v1/identity"
BROWSER_BOOTSTRAP_PATH: Final = "/v1/sites/bootstrap"
BROWSER_KEEPALIVE_PATH: Final = "/v1/sites/keepalive"
BROWSER_HEADERS_PATH: Final = "/v1/sites/headers"
BROWSER_FORGET_PATH: Final = "/v1/sites/forget"
BROWSER_LOGIN_START_PATH: Final = "/v1/logins/start"
BROWSER_LOGIN_FRAME_PATH: Final = "/v1/logins/frame"
BROWSER_LOGIN_INPUT_PATH: Final = "/v1/logins/input"
BROWSER_LOGIN_FINISH_PATH: Final = "/v1/logins/finish"
BROWSER_LOGIN_CANCEL_PATH: Final = "/v1/logins/cancel"

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


def login_associated_data(site: str, login_id: str) -> bytes:
    return f"site-session-login:v1:{site}:{login_id}".encode()


# Remote login (admin → broker → browser) -------------------------------------

LOGIN_WIDTH: Final = 1280
LOGIN_HEIGHT: Final = 800
LoginId = TaskId
Key = Literal[
    "Enter",
    "Backspace",
    "Tab",
    "Escape",
    "ArrowUp",
    "ArrowDown",
    "ArrowLeft",
    "ArrowRight",
]
_X = Field(default=None, ge=0, lt=LOGIN_WIDTH)
_Y = Field(default=None, ge=0, lt=LOGIN_HEIGHT)


class LoginAction(_Strict):
    """One pointer or keyboard step a human took in the remote login view."""

    kind: Literal["click", "drag", "wheel", "type", "key"]
    x: int | None = _X
    y: int | None = _Y
    x2: int | None = _X
    y2: int | None = _Y
    dy: int | None = Field(default=None, ge=-5000, le=5000)
    text: str | None = Field(default=None, min_length=1, max_length=256)
    key: Key | None = None

    @model_validator(mode="after")
    def _fields_match_kind(self) -> Self:
        required = {
            "click": ("x", "y"),
            "drag": ("x", "y", "x2", "y2"),
            "wheel": ("dy",),
            "type": ("text",),
            "key": ("key",),
        }[self.kind]
        present = {
            name
            for name in ("x", "y", "x2", "y2", "dy", "text", "key")
            if getattr(self, name) is not None
        }
        if present != set(required):
            raise ValueError(f"{self.kind} takes exactly {', '.join(required)}")
        return self


class LoginStartRequest(_Strict):
    site: Site
    url: Annotated[str, StringConstraints(max_length=2048)] | None = None


class LoginStarted(_Strict):
    login_id: LoginId
    site: Site
    width: int = LOGIN_WIDTH
    height: int = LOGIN_HEIGHT


class LoginRef(_Strict):
    login_id: LoginId


class LoginFrame(_Strict):
    image: Encoded
    host: Annotated[str, StringConstraints(max_length=253)]
    logged_in: bool


class LoginInputRequest(_Strict):
    login_id: LoginId
    actions: tuple[LoginAction, ...] = Field(min_length=1, max_length=20)


class LoginFinishRequest(_Strict):
    login_id: LoginId
    reply_key: Encoded


class LoginFinished(_Strict):
    site: Site
    jar: Encoded


class LoginSaved(_Strict):
    site: Site
    seed_revision: int = Field(ge=1)
