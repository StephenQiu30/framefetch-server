"""Read a site-scoped Cookie jar from local macOS Chrome.

Only the host source runs this; containers never read a host browser.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
import sys
from dataclasses import dataclass
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from typing import Protocol, cast

from app.workers.runner._secure_file import no_follow_flag
from yt_dlp import cookies as yt_dlp_cookies  # type: ignore[import-untyped]

DEFAULT_CHROME_ROOT = (
    Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
)
_PROFILE = re.compile(r"(?:Default|Profile [1-9][0-9]*)")
_DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?")
_CHROME_EPOCH_OFFSET_MICROSECONDS = 11_644_473_600 * 1_000_000


class _CookieDecryptor(Protocol):
    def decrypt(self, encrypted_value: bytes) -> str | None: ...


class _SilentLogger:
    def _ignore(self, *args: object, **kwargs: object) -> None:
        pass

    debug = info = warning = error = _ignore


def extract_chrome_cookies(
    domains: tuple[str, ...],
    profile: str = "Default",
    *,
    chrome_root: Path = DEFAULT_CHROME_ROOT,
) -> CookieJar:
    """Return only rows for explicitly allowlisted provider domains."""
    if sys.platform != "darwin":
        raise OSError("macOS Chrome Cookie extraction is unavailable")
    normalized = _validated_domains(domains)
    profile_dir = _safe_profile(chrome_root, profile)
    database = _cookie_database(profile_dir)
    return _read_filtered(database, chrome_root, normalized)


@dataclass(frozen=True, slots=True)
class ChromeProfile:
    directory: str
    display_name: str


def chrome_profiles(
    *, chrome_root: Path = DEFAULT_CHROME_ROOT
) -> tuple[ChromeProfile, ...]:
    """List real profile directories with the names Chrome shows the user."""
    _require_directory(chrome_root)
    names: dict[str, str] = {}
    try:
        state = json.loads((chrome_root / "Local State").read_text(encoding="utf-8"))
        cache = state.get("profile", {}).get("info_cache", {})
        names = {
            str(directory): str(info.get("name") or directory)
            for directory, info in cache.items()
            if isinstance(info, dict)
        }
    except (OSError, ValueError, AttributeError):
        pass
    profiles = []
    for entry in sorted(chrome_root.iterdir(), key=lambda path: path.name):
        if _PROFILE.fullmatch(entry.name) is None or entry.is_symlink():
            continue
        if entry.is_dir():
            profiles.append(
                ChromeProfile(entry.name, names.get(entry.name, entry.name))
            )
    return tuple(profiles)


def chrome_profile_directory(
    profile: str = "Default",
    *,
    chrome_root: Path = DEFAULT_CHROME_ROOT,
) -> Path:
    """Resolve one allowlisted Chrome profile without following symlinks."""
    return _safe_profile(chrome_root, profile)


def _safe_profile(chrome_root: Path, profile: str) -> Path:
    if _PROFILE.fullmatch(profile) is None:
        raise ValueError("unsafe Chrome profile name")
    _require_directory(chrome_root)
    profile_dir = chrome_root / profile
    _require_directory(profile_dir)
    return profile_dir


def _cookie_database(profile_dir: Path) -> Path:
    candidates: list[tuple[int, Path]] = []
    network = profile_dir / "Network"
    if _lexists(network):
        _require_directory(network)
    for candidate in (profile_dir / "Cookies", network / "Cookies"):
        if not _lexists(candidate):
            continue
        info = candidate.lstat()
        if candidate.is_symlink() or not stat.S_ISREG(info.st_mode):
            raise OSError("unsafe Chrome Cookie database")
        candidates.append((info.st_mtime_ns, candidate))
    if not candidates:
        raise FileNotFoundError("Chrome Cookie database was not found")
    return max(candidates, key=lambda item: item[0])[1]


def _read_filtered(
    database: Path,
    chrome_root: Path,
    domains: tuple[str, ...],
) -> CookieJar:
    before = database.lstat()
    # sqlite may collapse an operating-system privacy denial into a generic
    # OperationalError. Probe the already validated file so the source boundary
    # can distinguish a deployment permission problem from missing login data.
    descriptor = os.open(database, os.O_RDONLY | no_follow_flag())
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            raise OSError("unsafe Chrome Cookie database")
    finally:
        os.close(descriptor)
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
    try:
        current = database.lstat()
        if (
            database.is_symlink()
            or not stat.S_ISREG(current.st_mode)
            or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise OSError("unsafe Chrome Cookie database")
        connection.execute("PRAGMA query_only = ON")
        meta_row = connection.execute(
            "SELECT value FROM meta WHERE key = 'version'"
        ).fetchone()
        meta_version = int(meta_row[0]) if meta_row else 0
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(cookies)")
        }
        secure = "is_secure" if "is_secure" in columns else "secure"
        if secure not in columns:
            raise sqlite3.DatabaseError("unsupported Chrome Cookie schema")
        connection.text_factory = bytes
        clause = " OR ".join(
            "(lower(ltrim(host_key, '.')) = ? "
            "OR lower(ltrim(host_key, '.')) LIKE '%.' || ?)"
            for _ in domains
        )
        query = (
            "SELECT host_key, name, value, encrypted_value, path, "
            f"expires_utc, {secure} FROM cookies WHERE {clause}"
        )
        parameters = tuple(value for domain in domains for value in (domain, domain))
        rows = connection.execute(query, parameters)
        decryptor = _pinned_decryptor(chrome_root, meta_version)
        jar = CookieJar()
        encrypted = decrypted = 0
        for row in rows:
            if not row[2] and row[3]:
                encrypted += 1
            cookie = _to_cookie(decryptor, row)
            if cookie is not None:
                jar.set_cookie(cookie)
                decrypted += bool(not row[2] and row[3])
        if encrypted and not decrypted:
            # The pinned decryptor returns None when macOS withholds the
            # "Chrome Safe Storage" key; that is a permission problem, not a
            # missing login.
            raise PermissionError("Chrome Safe Storage key is unavailable")
        return jar
    finally:
        connection.close()


def _pinned_decryptor(chrome_root: Path, meta_version: int) -> _CookieDecryptor:
    """Narrow compatibility boundary for the commit-pinned yt-dlp package."""
    factory = getattr(yt_dlp_cookies, "get_cookie_decryptor", None)
    if not callable(factory):
        raise RuntimeError("pinned yt-dlp Cookie decryptor is unavailable")
    return cast(
        _CookieDecryptor,
        factory(str(chrome_root), "Chrome", _SilentLogger(), meta_version=meta_version),
    )


def _to_cookie(decryptor: _CookieDecryptor, row: tuple[object, ...]) -> Cookie | None:
    host, name, value, encrypted, path, expires, secure = row
    try:
        decoded_value = cast(bytes, value).decode()
        if not decoded_value and encrypted:
            decrypted = decryptor.decrypt(cast(bytes, encrypted))
            if decrypted is None:
                return None
            decoded_value = decrypted
        decoded_host = cast(bytes, host).decode()
        decoded_name = cast(bytes, name).decode()
        decoded_path = cast(bytes, path).decode()
    except Exception:
        return None
    expiry = _chrome_expiry(cast(int, expires))
    return Cookie(
        0,
        decoded_name,
        decoded_value,
        None,
        False,
        decoded_host,
        bool(decoded_host),
        decoded_host.startswith("."),
        decoded_path,
        bool(decoded_path),
        bool(secure),
        expiry,
        expiry is None,
        None,
        None,
        {},
        False,
    )


def _chrome_expiry(value: int) -> int | None:
    """Convert Chrome WebKit microseconds to the CookieJar Unix timestamp."""
    raw = int(value)
    if raw == 0:
        return None
    return max(0, (raw - _CHROME_EPOCH_OFFSET_MICROSECONDS) // 1_000_000)


def _require_directory(path: Path) -> None:
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
        raise OSError("unsafe Chrome profile path")


def _validated_domains(domains: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(value.casefold().lstrip(".") for value in domains))
    if not normalized or len(normalized) > 8:
        raise ValueError("invalid provider Cookie domain allowlist")
    if any(_DOMAIN.fullmatch(value) is None or ".." in value for value in normalized):
        raise ValueError("invalid provider Cookie domain allowlist")
    return normalized


def _lexists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True
