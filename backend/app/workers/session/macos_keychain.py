"""Read Chrome's existing storage key without allowing an authorization UI."""

from __future__ import annotations

import ctypes
import sys


class KeychainUnavailable(Exception):
    """The OS did not permit a noninteractive read; never request permission."""

    def __init__(self, status: int | None = None) -> None:
        super().__init__("Chrome storage key unavailable")
        self.status = status

    @property
    def access_denied(self) -> bool:
        return self.status in {-25293, -25308}


def chrome_storage_password() -> bytes:
    if sys.platform != "darwin":
        raise KeychainUnavailable()
    security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
    security.SecKeychainSetUserInteractionAllowed.argtypes = [ctypes.c_bool]
    security.SecKeychainSetUserInteractionAllowed.restype = ctypes.c_int32
    interaction_status = security.SecKeychainSetUserInteractionAllowed(False)
    if interaction_status != 0:
        raise KeychainUnavailable(interaction_status)
    security.SecKeychainFindGenericPassword.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
    ]
    security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
    security.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    security.SecKeychainItemFreeContent.restype = ctypes.c_int32
    service, account = b"Chrome Safe Storage", b"Chrome"
    size, value = ctypes.c_uint32(), ctypes.c_void_p()
    status = security.SecKeychainFindGenericPassword(
        None,
        len(service),
        service,
        len(account),
        account,
        ctypes.byref(size),
        ctypes.byref(value),
        None,
    )
    try:
        if status != 0 or not value.value or not 0 < size.value <= 16384:
            raise KeychainUnavailable(status)
        return ctypes.string_at(value, size.value)
    finally:
        if value.value:
            security.SecKeychainItemFreeContent(None, value)
