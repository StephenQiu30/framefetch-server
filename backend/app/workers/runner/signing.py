from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field

_NONCE = re.compile(r"[A-Za-z0-9_-]{16,128}")
_SIGNATURE = re.compile(r"[0-9a-f]{64}")


class RequestAuthenticationError(ValueError):
    """Base error for runner request authentication."""


class InvalidNonceError(RequestAuthenticationError):
    pass


class InvalidSignatureError(RequestAuthenticationError):
    pass


class ExpiredSignatureError(RequestAuthenticationError):
    pass


class ReplayDetectedError(RequestAuthenticationError):
    pass


class NonceCapacityError(RequestAuthenticationError):
    pass


@dataclass(slots=True)
class InMemoryNonceGuard:
    """Bounded process-local replay guard; production may provide a shared guard."""

    ttl_seconds: int
    max_entries: int
    _expirations: dict[str, int] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if self.ttl_seconds <= 0 or self.max_entries <= 0:
            raise ValueError("nonce guard limits must be positive")

    def claim(self, nonce: str, *, now: int) -> None:
        _validate_nonce(nonce)
        self._expirations = {
            value: expiry for value, expiry in self._expirations.items() if expiry > now
        }
        if nonce in self._expirations:
            raise ReplayDetectedError("nonce has already been used")
        if len(self._expirations) >= self.max_entries:
            raise NonceCapacityError("nonce guard is at capacity")
        self._expirations[nonce] = now + self.ttl_seconds


class HmacRequestAuthenticator:
    def __init__(
        self,
        secret: bytes,
        *,
        nonce_guard: InMemoryNonceGuard,
        max_age_seconds: int,
        max_future_skew_seconds: int,
    ) -> None:
        _validate_secret(secret)
        if max_age_seconds <= 0 or max_future_skew_seconds < 0:
            raise ValueError("signature time limits are invalid")
        if nonce_guard.ttl_seconds <= max_age_seconds + max_future_skew_seconds:
            raise ValueError("nonce TTL must exceed the full signature time window")
        self._secret = secret
        self._nonce_guard = nonce_guard
        self._max_age = max_age_seconds
        self._future_skew = max_future_skew_seconds

    def sign(
        self,
        method: str,
        target: str,
        body: bytes,
        timestamp: int,
        nonce: str,
        *,
        runtime_instance_id: str | None = None,
    ) -> str:
        return sign_request(
            self._secret,
            method,
            target,
            body,
            timestamp,
            nonce,
            runtime_instance_id=runtime_instance_id,
        )

    def verify(
        self,
        method: str,
        target: str,
        body: bytes,
        timestamp: int,
        nonce: str,
        signature: str,
        *,
        now: int,
        runtime_instance_id: str | None = None,
    ) -> None:
        payload = _canonical_request(
            method, target, body, timestamp, nonce, runtime_instance_id
        )
        if timestamp < now - self._max_age or timestamp > now + self._future_skew:
            raise ExpiredSignatureError(
                "signature timestamp is outside the time window"
            )
        if not isinstance(signature, str) or _SIGNATURE.fullmatch(signature) is None:
            raise InvalidSignatureError("signature does not match")
        expected = hmac.new(self._secret, payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise InvalidSignatureError("signature does not match")
        self._nonce_guard.claim(nonce, now=now)


def _canonical_request(
    method: str,
    target: str,
    body: bytes,
    timestamp: int,
    nonce: str,
    runtime_instance_id: str | None,
) -> bytes:
    if not method or not method.isascii() or not method.isalpha():
        raise RequestAuthenticationError("HTTP method is invalid")
    if not target.startswith("/") or any(ord(char) <= 32 for char in target):
        raise RequestAuthenticationError("request target is invalid")
    if not isinstance(body, bytes):
        raise RequestAuthenticationError("request body must be bytes")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        raise RequestAuthenticationError("timestamp must be integer seconds")
    _validate_nonce(nonce)
    body_hash = hashlib.sha256(body).hexdigest()
    if (
        runtime_instance_id is not None
        and re.fullmatch(r"[0-9a-f]{32}", runtime_instance_id) is None
    ):
        raise RequestAuthenticationError("runtime instance is invalid")
    fields = (
        method.upper(),
        target,
        str(timestamp),
        nonce,
        body_hash,
        runtime_instance_id or "",
    )
    return "\n".join(fields).encode("utf-8")


def sign_request(
    secret: bytes,
    method: str,
    target: str,
    body: bytes,
    timestamp: int,
    nonce: str,
    *,
    runtime_instance_id: str | None = None,
) -> str:
    """Create the canonical signature without mutating replay state."""
    _validate_secret(secret)
    payload = _canonical_request(
        method, target, body, timestamp, nonce, runtime_instance_id
    )
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _validate_nonce(nonce: str) -> None:
    if not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None:
        raise InvalidNonceError("nonce must be 16-128 base64url characters")


def _validate_secret(secret: bytes) -> None:
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise ValueError("HMAC secret must contain at least 32 bytes")
