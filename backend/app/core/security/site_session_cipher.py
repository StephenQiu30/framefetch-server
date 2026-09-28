"""Bind encrypted site session jars to their site, import and rotation version."""

from cryptography.fernet import Fernet, InvalidToken


class SiteSessionCipher:
    def __init__(self, key: str) -> None:
        self._cipher = Fernet(key.encode("ascii"))

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
