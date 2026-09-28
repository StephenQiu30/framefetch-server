"""X25519 + HKDF + ChaCha20-Poly1305 sealed boxes for site session material.

Every seal uses a fresh ephemeral sender key; the associated data binds the
payload to its purpose (task, site, import revision and deadline) so a sealed
jar cannot be replayed into another task, site or direction.
"""

from __future__ import annotations

import base64
import os
from typing import Final

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PUBLIC_KEY_BYTES: Final = 32
NONCE_BYTES: Final = 12
MAX_PAYLOAD_BYTES: Final = 1024**2
_VERSION: Final = b"\x01"
_INFO: Final = b"framefetch-site-session-seal-v1"


class SealError(ValueError):
    """The sealed payload is malformed, tampered or bound to another purpose."""


def public_key(private_key: X25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def decode(value: str, *, limit: int = MAX_PAYLOAD_BYTES * 2) -> bytes:
    if len(value) > limit:
        raise SealError("encoded value is too large")
    try:
        return base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except (ValueError, UnicodeEncodeError) as exc:
        raise SealError("invalid encoding") from exc


def decode_public_key(value: str) -> bytes:
    decoded = decode(value, limit=64)
    if len(decoded) != PUBLIC_KEY_BYTES:
        raise SealError("invalid public key")
    return decoded


def seal(payload: bytes, recipient: bytes, *, associated_data: bytes) -> bytes:
    if not 0 < len(payload) <= MAX_PAYLOAD_BYTES:
        raise SealError("payload size is out of bounds")
    try:
        peer = X25519PublicKey.from_public_bytes(recipient)
    except ValueError as exc:
        raise SealError("invalid public key") from exc
    ephemeral = X25519PrivateKey.generate()
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = ChaCha20Poly1305(_key(ephemeral.exchange(peer))).encrypt(
        nonce, payload, associated_data
    )
    return _VERSION + public_key(ephemeral) + nonce + ciphertext


def open_sealed(
    sealed: bytes, private_key: X25519PrivateKey, *, associated_data: bytes
) -> bytes:
    header = len(_VERSION) + PUBLIC_KEY_BYTES + NONCE_BYTES
    if (
        not sealed.startswith(_VERSION)
        or len(sealed) < header + 16
        or len(sealed) > header + 16 + MAX_PAYLOAD_BYTES
    ):
        raise SealError("malformed sealed payload")
    sender = sealed[len(_VERSION) : len(_VERSION) + PUBLIC_KEY_BYTES]
    nonce = sealed[header - NONCE_BYTES : header]
    try:
        peer = X25519PublicKey.from_public_bytes(sender)
        return ChaCha20Poly1305(_key(private_key.exchange(peer))).decrypt(
            nonce, sealed[header:], associated_data
        )
    except Exception as exc:
        raise SealError("sealed payload cannot be opened") from exc


def _key(shared: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(
        shared
    )
