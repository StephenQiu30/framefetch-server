"""Bind encrypted site session jars to their site, import and rotation version."""

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken


class SiteSessionCipher:
    def __init__(self, key: str) -> None:
        self._cipher = Fernet(key.encode("ascii"))
        self._fingerprint_key = base64.urlsafe_b64decode(key)

    def source_fingerprint(self, site: str, payload: bytes) -> str:
        """Private, keyed identity marker; never expose it in public status."""
        return hmac.new(
            self._fingerprint_key,
            b"site-source:v1\0" + site.encode() + b"\0" + payload,
            hashlib.sha256,
        ).hexdigest()

    def encrypt(
        self, site: str, seed_revision: int, jar_version: int, payload: bytes
    ) -> bytes:
        if not payload:
            raise ValueError("empty site session payload")
        return self._cipher.encrypt(
            _binding(site, seed_revision, jar_version) + payload
        )

    def decrypt(
        self, site: str, seed_revision: int, jar_version: int, ciphertext: bytes
    ) -> bytes:
        try:
            plaintext = self._cipher.decrypt(ciphertext)
        except InvalidToken:
            raise ValueError("invalid site session ciphertext") from None
        binding = _binding(site, seed_revision, jar_version)
        # A ciphertext copied to another row or version must never decrypt.
        if not plaintext.startswith(binding):
            raise ValueError("site session binding mismatch")
        return plaintext[len(binding) :]


def _binding(site: str, seed_revision: int, jar_version: int) -> bytes:
    if not site or "\n" in site or seed_revision < 1 or jar_version < 0:
        raise ValueError("invalid site session binding")
    return f"site-session:{site}:{seed_revision}:{jar_version}\n".encode()
