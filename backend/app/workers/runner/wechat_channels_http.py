"""Runner-only transport for one fixed Chrome HTTP Yuanbao share parse."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from app.services.provider_failures import FailureClass
from app.services.provider_types import ProviderIdentity
from app.workers.identity.yuanbao_parse import (
    YUANBAO_ORIGIN,
    YUANBAO_PARSE_MAX_MESSAGE_BYTES,
    YUANBAO_PARSE_TIMEOUT,
    validate_canonical_share_url,
    validate_yuanbao_parse_result,
)
from app.workers.runner.engine.identity import YuanbaoRequestIdentity
from app.workers.runner.engine.layers.base import LayerFailure
from app.workers.runner.provider_registry import provider_profile_for_key
from app.workers.runner.settings import get_runner_settings

_MAX_RESPONSE_BYTES = YUANBAO_PARSE_MAX_MESSAGE_BYTES
_TRANSPORT_TIMEOUT = YUANBAO_PARSE_TIMEOUT + 2.0
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_CAUSE_CLASSES = {
    "credential_missing": FailureClass.LOGIN_REQUIRED,
    "identity_account_conflict": FailureClass.CONTEXT_CHANGED,
    "identity_material_invalid": FailureClass.IDENTITY_UNAVAILABLE,
    "extension_disconnected": FailureClass.IDENTITY_UNAVAILABLE,
    "extension_timeout": FailureClass.IDENTITY_UNAVAILABLE,
    "identity_deadline_invalid": FailureClass.IDENTITY_UNAVAILABLE,
    "identity_source_mismatch": FailureClass.IDENTITY_UNAVAILABLE,
    "parse_response_invalid": FailureClass.EXTRACTOR_BROKEN,
    "yuanbao_response_source_invalid": FailureClass.EXTRACTOR_BROKEN,
    "yuanbao_response_size_invalid": FailureClass.EXTRACTOR_BROKEN,
    "yuanbao_response_utf8_invalid": FailureClass.EXTRACTOR_BROKEN,
    "yuanbao_response_json_invalid": FailureClass.EXTRACTOR_BROKEN,
    "yuanbao_response_credential_echo": FailureClass.EXTRACTOR_BROKEN,
    "parse_request_failed": FailureClass.TRANSIENT,
}


@dataclass(frozen=True, slots=True)
class ShareParseResult:
    identity: YuanbaoRequestIdentity
    captured: Mapping[str, Any] = field(repr=False)


def _failure(
    cause: str,
    kind: FailureClass = FailureClass.IDENTITY_UNAVAILABLE,
    gate: Literal["①", "②", "③", "none"] = "③",
) -> LayerFailure:
    return LayerFailure(
        kind,
        gate,
        {
            "kind": "upstream_response" if gate == "②" else "runtime",
            "cause_code": cause,
        },
    )


def _invalid_response() -> LayerFailure:
    return _failure("parse_response_invalid", FailureClass.EXTRACTOR_BROKEN, "②")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise ValueError("non-finite JSON number")


def _decode(raw: bytes | bytearray) -> object:
    return json.loads(
        raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
    )


async def parse_yuanbao_share(
    canonical_url: str, task_id: str, deadline: datetime
) -> ShareParseResult:
    """Obtain a captured parse without exporting Chrome account credentials."""
    try:
        validate_canonical_share_url(canonical_url)
    except (ValueError, TypeError):
        raise _failure(
            "yuanbao_share_invalid", FailureClass.INVALID_INPUT, "none"
        ) from None
    if not isinstance(task_id, str) or _TASK_ID.fullmatch(task_id) is None:
        raise _failure("identity_task_invalid", FailureClass.INVALID_INPUT, "none")
    if not isinstance(deadline, datetime) or deadline.utcoffset() is None:
        raise _failure("identity_deadline_invalid", FailureClass.INVALID_INPUT, "none")
    remaining = (deadline - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise _failure("identity_deadline_invalid", FailureClass.INVALID_INPUT, "none")
    profile = provider_profile_for_key("wechat_channels")
    if (
        profile.key != "wechat_channels"
        or profile.identity_source != "yuanbao_http"
        or profile.identity_origin != YUANBAO_ORIGIN
        or profile.content_scope != "official_share"
        or profile.identity is not ProviderIdentity.REQUIRED
        or profile.cookie_domain_allowlist
    ):
        raise _failure("identity_source_mismatch")
    settings = get_runner_settings()
    if settings.cookie_source_token is None:
        raise _failure("identity_not_configured")
    endpoint = (
        f"http://host.docker.internal:{settings.cookie_source_port}/yuanbao-parse"
    )
    timeout = min(_TRANSPORT_TIMEOUT, remaining)
    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(
                # The host bridge follows the existing proxy's always_direct
                # host rule, independently of the platform's egress binding.
                proxy=settings.runner_egress_proxy,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(timeout, connect=min(5.0, timeout)),
            ) as client:
                async with client.stream(
                    "POST",
                    endpoint,
                    headers={
                        "Authorization": (
                            f"Bearer {settings.cookie_source_token.get_secret_value()}"
                        )
                    },
                    json={
                        "site": "wechat_channels",
                        "canonical_share_url": canonical_url,
                        "task_id": task_id,
                        "deadline": deadline.astimezone(UTC).isoformat(),
                    },
                ) as response:
                    if 300 <= response.status_code < 400:
                        raise _failure("cookie_source_rejected")
                    length = response.headers.get("content-length")
                    if length is not None and (
                        len(length) > 20
                        or not length.isascii()
                        or not length.isdigit()
                        or int(length) > _MAX_RESPONSE_BYTES
                    ):
                        raise _invalid_response()
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > _MAX_RESPONSE_BYTES:
                            raise _invalid_response()
                        raw.extend(chunk)
                    try:
                        decoded = _decode(raw)
                    except (ValueError, TypeError, RecursionError):
                        raise _invalid_response() from None
                    if response.status_code != 200:
                        cause = (
                            decoded.get("cause")
                            if isinstance(decoded, dict) and set(decoded) == {"cause"}
                            else None
                        )
                        if not isinstance(cause, str) or cause not in _CAUSE_CLASSES:
                            raise _failure("cookie_source_rejected")
                        kind = _CAUSE_CLASSES[cause]
                        raise _failure(
                            cause,
                            kind,
                            "②"
                            if kind
                            in {FailureClass.EXTRACTOR_BROKEN, FailureClass.TRANSIENT}
                            else "③",
                        )
                    if datetime.now(UTC) >= deadline:
                        raise _failure("identity_deadline_invalid")
                    try:
                        parsed = validate_yuanbao_parse_result(
                            decoded, canonical_share_url=canonical_url
                        )
                        result = ShareParseResult(
                            YuanbaoRequestIdentity(parsed.identity_digest),
                            parsed.captured.model_dump(mode="json"),
                        )
                    except (ValueError, TypeError, RecursionError):
                        raise _invalid_response() from None
                    if datetime.now(UTC) >= deadline:
                        raise _failure("identity_deadline_invalid")
                    return result
    except asyncio.CancelledError:
        raise
    except LayerFailure:
        raise
    except (TimeoutError, httpx.TimeoutException):
        raise _failure("extension_timeout") from None
    except httpx.HTTPError:
        raise _failure("cookie_source_unavailable") from None
