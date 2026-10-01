"""Domain-separated encryption for administrator-supplied AI credentials."""

from __future__ import annotations

import hmac

from app.core.security.url_cipher import URLCipher


class FernetAiProviderSecretCipher:
    def __init__(self, cipher: URLCipher, *, key_id: str) -> None:
        if not key_id.strip():
            raise ValueError("AI Provider encryption key id cannot be blank")
        self._cipher = cipher
        self._key_id = key_id

    @property
    def key_id(self) -> str:
        return self._key_id

    def encrypt(self, provider_key: str, secret: str) -> bytes:
        if not provider_key.strip() or not secret.strip():
            raise ValueError("AI Provider key and secret cannot be blank")
        return self._cipher.encrypt(f"ai-provider:{provider_key}:{secret}")

    def decrypt(self, provider_key: str, ciphertext: bytes, key_id: str) -> str:
        if not hmac.compare_digest(key_id, self._key_id):
            raise ValueError("unknown AI Provider encryption key id")
        prefix = f"ai-provider:{provider_key}:"
        plaintext = self._cipher.decrypt(ciphertext)
        if not plaintext.startswith(prefix):
            raise ValueError("AI Provider credential binding does not match")
        return plaintext[len(prefix) :]
