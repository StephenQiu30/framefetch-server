"""Fixed first-party Yuanbao capture and account-bound Chrome HTTP result."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

YUANBAO_ORIGIN = "https://yuanbao.tencent.com"
YUANBAO_PARSE_URL = YUANBAO_ORIGIN + "/api/weixin/get_parse_result"
YUANBAO_PARSE_TIMEOUT = 30.0
YUANBAO_PARSE_MAX_BYTES = 4 * 1024**2
YUANBAO_PARSE_MAX_MESSAGE_BYTES = YUANBAO_PARSE_MAX_BYTES + 4096


def validate_canonical_share_url(value: object) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"https://weixin\.qq\.com/sph/[A-Za-z0-9_-]{4,256}", value)
        is None
    ):
        raise ValueError("invalid share URL")
    return value


class YuanbaoParseBody(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal["video_channel_url"]
    url: str = Field(strict=True)
    scene: int = Field(strict=True, ge=1, le=1)


class YuanbaoCapturedParse(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    request_method: Literal["POST"]
    request_url: Literal["https://yuanbao.tencent.com/api/weixin/get_parse_result"]
    response_url: Literal["https://yuanbao.tencent.com/api/weixin/get_parse_result"]
    http_status: int = Field(strict=True, ge=200, le=599)
    request_body: YuanbaoParseBody
    payload: dict[str, Any] = Field(repr=False)


class YuanbaoParseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    identity_digest: str = Field(strict=True, pattern=r"^[a-f0-9]{64}$")
    captured: YuanbaoCapturedParse = Field(repr=False)


def _account_identifier(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError("invalid account identifier")
    try:
        if len(value.encode("utf-8")) > 1024:
            raise ValueError("invalid account identifier")
    except UnicodeEncodeError:
        raise ValueError("invalid account identifier") from None
    return value


class _YuanbaoOracleResult(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    account_id: SecretStr = Field(repr=False)
    captured: YuanbaoCapturedParse = Field(repr=False)

    @field_validator("account_id", mode="before")
    @classmethod
    def account_identifier(cls, value: object) -> str:
        return _account_identifier(value)


def _validate_capture(captured: YuanbaoCapturedParse, canonical_share_url: str) -> None:
    expected = validate_canonical_share_url(canonical_share_url)
    if captured.request_body.url != expected:
        raise ValueError("response share mismatch")
    encoded = json.dumps(
        captured.model_dump(),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > YUANBAO_PARSE_MAX_BYTES:
        raise ValueError("response too large")


def stable_yuanbao_identity_digest(account_id: str, *, key: str) -> str:
    if not isinstance(key, str) or not key:
        raise ValueError("invalid digest key")
    canonical = json.dumps(
        [
            "yuanbao_http",
            YUANBAO_ORIGIN,
            "wechat_channels",
            _account_identifier(account_id),
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def validate_yuanbao_oracle_result(
    raw: object, *, canonical_share_url: str, key: str
) -> YuanbaoParseResult:
    parsed = _YuanbaoOracleResult.model_validate(raw)
    _validate_capture(parsed.captured, canonical_share_url)
    return YuanbaoParseResult(
        identity_digest=stable_yuanbao_identity_digest(
            parsed.account_id.get_secret_value(), key=key
        ),
        captured=parsed.captured,
    )


def validate_yuanbao_parse_result(
    raw: object, *, canonical_share_url: str
) -> YuanbaoParseResult:
    result = YuanbaoParseResult.model_validate(raw)
    _validate_capture(result.captured, canonical_share_url)
    return result
