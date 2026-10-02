"""Pure validation for the operation-scoped Yuanbao account transport."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
)

YUANBAO_ORIGIN = "https://yuanbao.tencent.com"
YUANBAO_ACCOUNT_ID_MAX_BYTES = 1024
YUANBAO_AUTH_TOKEN_MAX_BYTES = 8192


class YuanbaoAccountPayload(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    origin: Literal["https://yuanbao.tencent.com"]
    account_id: SecretStr = Field(repr=False)
    auth_token: SecretStr = Field(repr=False)

    @field_validator("account_id", "auth_token", mode="before")
    @classmethod
    def validate_account_field(cls, value: object, info: ValidationInfo) -> str:
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        limit = (
            YUANBAO_ACCOUNT_ID_MAX_BYTES
            if info.field_name == "account_id"
            else YUANBAO_AUTH_TOKEN_MAX_BYTES
        )
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("invalid account field")
        try:
            if len(value.encode("utf-8")) > limit:
                raise ValueError("account field too large")
        except UnicodeEncodeError:
            raise ValueError("invalid account field") from None
        return value


class YuanbaoAccountMaterial(YuanbaoAccountPayload):
    kind: Literal["yuanbao_account"]
    digest: str = Field(strict=True, pattern=r"^[a-f0-9]{64}$")
    local_use_deadline: AwareDatetime

    @field_validator("local_use_deadline", mode="before")
    @classmethod
    def validate_deadline_input(cls, value: object) -> object:
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value
        ):
            raise ValueError("invalid account deadline")
        return value

    @field_validator("local_use_deadline")
    @classmethod
    def validate_utc_deadline(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("account deadline must be UTC")
        return value.astimezone(UTC)


def validate_yuanbao_account_payload(payload: object) -> YuanbaoAccountPayload:
    return YuanbaoAccountPayload.model_validate(payload)


def stable_yuanbao_account_digest(
    payload: YuanbaoAccountPayload, *, site: str, key: str
) -> str:
    """Bind stable source/account material, never dynamic proof or operation time."""
    if site != "wechat_channels" or not isinstance(key, str) or not key:
        raise ValueError("invalid account digest context")
    account = YuanbaoAccountPayload(
        origin=payload.origin,
        account_id=payload.account_id,
        auth_token=payload.auth_token,
    )
    canonical = json.dumps(
        [
            "yuanbao_account",
            account.origin,
            site,
            account.account_id.get_secret_value(),
            account.auth_token.get_secret_value(),
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def validate_yuanbao_account_material(
    payload: object, *, deadline: datetime, now: datetime | None = None
) -> YuanbaoAccountMaterial:
    """A local operation cap is not the remote token's expiry."""
    current = now or datetime.now(UTC)
    if (
        deadline.utcoffset() is None
        or current.utcoffset() is None
        or deadline <= current
    ):
        raise ValueError("invalid operation deadline")
    material = YuanbaoAccountMaterial.model_validate(payload)
    if not current < material.local_use_deadline <= deadline:
        raise ValueError("invalid account use deadline")
    return material
