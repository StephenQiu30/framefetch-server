"""Native ABI and denial paths use fake C functions; no real Keychain is read."""

import ctypes
from types import SimpleNamespace

import pytest
from app.workers.session import macos_keychain


class NativeFunction:
    def __init__(self, callback):
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


class SecurityFixture:
    def __init__(self, *, status=0, size=None, data=True, interaction_status=0):
        self.password = b"synthetic-storage\x00key"
        self.buffer = ctypes.create_string_buffer(self.password)
        self.status = status
        self.size = len(self.password) if size is None else size
        self.data = data
        self.interaction_status = interaction_status
        self.calls = []
        self.SecKeychainSetUserInteractionAllowed = NativeFunction(self.interaction)
        self.SecKeychainFindGenericPassword = NativeFunction(self.find)
        self.SecKeychainItemFreeContent = NativeFunction(self.free)

    def interaction(self, allowed):
        self.calls.append(("interaction", allowed))
        return self.interaction_status

    def find(
        self, keychain, service_size, service, account_size, account, size, data, item
    ):
        self.calls.append(
            ("find", keychain, service_size, service, account_size, account, item)
        )
        ctypes.cast(size, ctypes.POINTER(ctypes.c_uint32))[0] = self.size
        if self.data:
            ctypes.cast(data, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.addressof(
                self.buffer
            )
        return self.status

    def free(self, attributes, data):
        self.calls.append(("free", attributes, data.value))
        return 0


def install_fake_security(monkeypatch, fixture, platform="darwin"):
    monkeypatch.setattr(macos_keychain, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(
        macos_keychain,
        "ctypes",
        SimpleNamespace(
            CDLL=lambda _: fixture,
            c_bool=ctypes.c_bool,
            c_int32=ctypes.c_int32,
            c_uint32=ctypes.c_uint32,
            c_void_p=ctypes.c_void_p,
            c_char_p=ctypes.c_char_p,
            POINTER=ctypes.POINTER,
            byref=ctypes.byref,
            string_at=ctypes.string_at,
        ),
    )


def test_native_lookup_disables_interaction_first_and_preserves_binary_length(
    monkeypatch,
):
    fixture = SecurityFixture()
    install_fake_security(monkeypatch, fixture)
    assert macos_keychain.chrome_storage_password() == fixture.password
    assert fixture.calls == [
        ("interaction", False),
        ("find", None, 19, b"Chrome Safe Storage", 6, b"Chrome", None),
        ("free", None, ctypes.addressof(fixture.buffer)),
    ]
    assert fixture.SecKeychainFindGenericPassword.argtypes[-3:-1] == [
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    assert fixture.SecKeychainFindGenericPassword.restype is ctypes.c_int32
    assert fixture.SecKeychainSetUserInteractionAllowed.argtypes == [ctypes.c_bool]


def test_cannot_disable_interaction_never_attempts_key_lookup(monkeypatch):
    fixture = SecurityFixture(interaction_status=-1)
    install_fake_security(monkeypatch, fixture)
    with pytest.raises(macos_keychain.KeychainUnavailable):
        macos_keychain.chrome_storage_password()
    assert fixture.calls == [("interaction", False)]


@pytest.mark.parametrize(
    "options",
    [
        {"status": -25308},
        {"status": -25300},
        {"size": 0},
        {"size": 16385},
    ],
)
def test_unavailable_or_invalid_native_result_is_freed_without_exposing_it(
    options, monkeypatch
):
    fixture = SecurityFixture(**options)
    install_fake_security(monkeypatch, fixture)
    with pytest.raises(macos_keychain.KeychainUnavailable) as error:
        macos_keychain.chrome_storage_password()
    assert error.value.status == options.get("status", 0)
    assert b"synthetic-storage" not in str(error.value).encode()
    assert fixture.calls[-1] == ("free", None, ctypes.addressof(fixture.buffer))


def test_null_native_result_is_never_dereferenced_or_freed(monkeypatch):
    fixture = SecurityFixture(data=False)
    install_fake_security(monkeypatch, fixture)
    with pytest.raises(macos_keychain.KeychainUnavailable):
        macos_keychain.chrome_storage_password()
    assert [call[0] for call in fixture.calls] == ["interaction", "find"]


def test_nonmacos_fails_before_loading_security_library(monkeypatch):
    fixture = SecurityFixture()
    install_fake_security(monkeypatch, fixture, platform="linux")
    with pytest.raises(macos_keychain.KeychainUnavailable):
        macos_keychain.chrome_storage_password()
    assert fixture.calls == []


@pytest.mark.parametrize(
    ("status", "denied"),
    [(-25293, True), (-25308, True), (-25300, False), (0, False), (None, False)],
)
def test_missing_item_and_invalid_result_do_not_claim_os_denial(status, denied):
    assert macos_keychain.KeychainUnavailable(status).access_denied is denied
