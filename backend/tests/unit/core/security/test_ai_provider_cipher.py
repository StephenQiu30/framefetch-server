import pytest
from app.core.security.ai_provider_cipher import FernetAiProviderSecretCipher
from app.core.security.url_cipher import URLCipher
from app.services.identifiers import UrlEncryptionKeyId
from cryptography.fernet import Fernet


def test_ai_provider_secret_is_bound_to_profile_and_key_version() -> None:
    cipher = FernetAiProviderSecretCipher(
        URLCipher(Fernet.generate_key()), key_id=UrlEncryptionKeyId.FERNET
    )
    encrypted = cipher.encrypt("primary", "secret-value")

    assert (
        cipher.decrypt("primary", encrypted, UrlEncryptionKeyId.FERNET)
        == "secret-value"
    )
    with pytest.raises(ValueError, match="key id"):
        cipher.decrypt("primary", encrypted, UrlEncryptionKeyId.LEGACY_FERNET)
    with pytest.raises(ValueError):
        cipher.decrypt("secondary", encrypted, UrlEncryptionKeyId.FERNET)
    with pytest.raises(ValueError):
        cipher.decrypt("primary", encrypted, "unknown")
