import pytest
from app.workers.session.sealing import (
    SealError,
    decode,
    decode_public_key,
    encode,
    open_sealed,
    public_key,
    seal,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey


def test_sealed_payload_opens_only_for_its_key_and_purpose():
    key = X25519PrivateKey.generate()
    sealed = seal(b"jar", public_key(key), associated_data=b"task-1")
    assert open_sealed(sealed, key, associated_data=b"task-1") == b"jar"
    assert seal(b"jar", public_key(key), associated_data=b"task-1") != sealed
    with pytest.raises(SealError):
        open_sealed(sealed, key, associated_data=b"task-2")
    with pytest.raises(SealError):
        open_sealed(sealed, X25519PrivateKey.generate(), associated_data=b"task-1")
    tampered = sealed[:-1] + bytes([sealed[-1] ^ 1])
    with pytest.raises(SealError):
        open_sealed(tampered, key, associated_data=b"task-1")
    for malformed in (b"", b"\x02" + sealed[1:], sealed[:40]):
        with pytest.raises(SealError):
            open_sealed(malformed, key, associated_data=b"task-1")


def test_payload_and_key_bounds():
    key = public_key(X25519PrivateKey.generate())
    with pytest.raises(SealError):
        seal(b"", key, associated_data=b"")
    with pytest.raises(SealError):
        seal(b"x" * (1024**2 + 1), key, associated_data=b"")
    with pytest.raises(SealError):
        seal(b"x", b"short", associated_data=b"")


def test_encoding_round_trip_and_validation():
    key = public_key(X25519PrivateKey.generate())
    assert decode_public_key(encode(key)) == key
    assert decode(encode(b"\x00\xff")) == b"\x00\xff"
    for bad in ("***", encode(b"short"), "A" * 100):
        with pytest.raises(SealError):
            decode_public_key(bad)
