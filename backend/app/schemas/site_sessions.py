"""Admin views of deployment site sessions and the remote login relay."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from app.schemas.common import StrictModel
from app.services.site_sessions import SiteSessionState

_X = Field(default=None, ge=0, lt=1280)
_Y = Field(default=None, ge=0, lt=800)


class SiteSessionResponse(StrictModel):
    site: str
    provider_key: str | None
    state: SiteSessionState | None = Field(
        description="空表示该平台尚未登录；revoked 表示已撤销"
    )
    seed_revision: int | None
    verified_at: datetime | None
    refreshed_at: datetime | None
    last_error_code: str | None
    proves_login: bool = Field(
        description="保活能确认真实登录；否则只能确认登录 Cookie 仍被保留"
    )


class SiteSessionListResponse(StrictModel):
    items: tuple[SiteSessionResponse, ...]


class StartSiteSessionLoginRequest(StrictModel):
    target: Annotated[str, StringConstraints(min_length=3, max_length=2048)] = Field(
        description="已知站点（如 weixin.qq.com）、域名，或任意 https 页面链接"
    )


class SiteSessionLoginResponse(StrictModel):
    login_id: str
    site: str
    width: int
    height: int


class SiteSessionLoginFrameResponse(StrictModel):
    image: str = Field(description="JPEG 画面的 base64")
    host: str
    logged_in: bool


class SiteSessionLoginAction(StrictModel):
    kind: Literal["click", "drag", "wheel", "type", "key"]
    x: int | None = _X
    y: int | None = _Y
    x2: int | None = _X
    y2: int | None = _Y
    dy: int | None = Field(default=None, ge=-5000, le=5000)
    text: Annotated[str, StringConstraints(min_length=1, max_length=256)] | None = None
    key: (
        Literal[
            "Enter",
            "Backspace",
            "Tab",
            "Escape",
            "ArrowUp",
            "ArrowDown",
            "ArrowLeft",
            "ArrowRight",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def _fields_match_kind(self) -> "SiteSessionLoginAction":
        required = {
            "click": {"x", "y"},
            "drag": {"x", "y", "x2", "y2"},
            "wheel": {"dy"},
            "type": {"text"},
            "key": {"key"},
        }[self.kind]
        present = {
            name
            for name in ("x", "y", "x2", "y2", "dy", "text", "key")
            if getattr(self, name) is not None
        }
        if present != required:
            raise ValueError(f"{self.kind} takes exactly {', '.join(sorted(required))}")
        return self


class SiteSessionLoginInputRequest(StrictModel):
    actions: tuple[SiteSessionLoginAction, ...] = Field(min_length=1, max_length=20)


class SiteSessionLoginSavedResponse(StrictModel):
    site: str
    seed_revision: int
