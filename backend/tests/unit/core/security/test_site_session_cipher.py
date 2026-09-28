import pytest
from app.core.security.site_session_cipher import SiteSessionCipher
from cryptography.fernet import Fernet


def test_ciphertext_is_bound_to_site_import_and_rotation() -> None:
    cipher = SiteSessionCipher(Fernet.generate_key().decode())
    ciphertext = cipher.encrypt("youtube.com", 2, 5, b"jar")
    assert cipher.decrypt("youtube.com", 2, 5, ciphertext) == b"jar"
    for site, seed, jar in (
        ("reddit.com", 2, 5),
        ("youtube.com", 1, 5),
        ("youtube.com", 2, 4),
    ):
        with pytest.raises(ValueError):
            cipher.decrypt(site, seed, jar, ciphertext)
    other = SiteSessionCipher(Fernet.generate_key().decode())
    with pytest.raises(ValueError):
        other.decrypt("youtube.com", 2, 5, ciphertext)


@pytest.mark.parametrize(
    ("site", "seed", "jar", "payload"),
    [
        ("", 1, 0, b"x"),
        ("a\nb", 1, 0, b"x"),
        ("a.com", 0, 0, b"x"),
        ("a.com", 1, -1, b"x"),
        ("a.com", 1, 0, b""),
    ],
)
def test_invalid_bindings_are_rejected(site, seed, jar, payload) -> None:
    cipher = SiteSessionCipher(Fernet.generate_key().decode())
    with pytest.raises(ValueError):
        cipher.encrypt(site, seed, jar, payload)
