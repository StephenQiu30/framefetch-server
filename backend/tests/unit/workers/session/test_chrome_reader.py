from __future__ import annotations

import sqlite3
from http.cookiejar import CookieJar
from pathlib import Path

import pytest
from app.workers.session import chrome_reader as chrome


class _Decryptor:
    def __init__(self) -> None:
        self.values: list[bytes] = []

    def decrypt(self, value: bytes) -> str | None:
        self.values.append(value)
        if value == b"youtube-encrypted":
            return "youtube-value"
        if value == b"instagram-encrypted":
            return "instagram-value"
        raise AssertionError("a non-allowlisted Cookie reached the decryptor")


def _database(path: Path, *, secure_column: str = "is_secure") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        f"""
        CREATE TABLE meta (
          key LONGVARCHAR NOT NULL UNIQUE PRIMARY KEY, value LONGVARCHAR
        );
        INSERT INTO meta VALUES ('version', '24');
        CREATE TABLE cookies (
          host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB, path TEXT,
          expires_utc INTEGER, {secure_column} INTEGER
        );
        """
    )
    connection.executemany(
        "INSERT INTO cookies VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            (".youtube.com", "session", "", b"youtube-encrypted", "/", 9, 1),
            ("embed.youtube-nocookie.com", "embed", "plain", b"", "/", 0, 1),
            ("accounts.google.com", "account", "", b"google-encrypted", "/", 9, 1),
            ("notyoutube.com", "other", "", b"other-encrypted", "/", 9, 1),
            ("youtube.com.attacker.test", "fake", "", b"fake-encrypted", "/", 9, 1),
            (".instagram.com", "sessionid", "", b"instagram-encrypted", "/", 9, 1),
        ),
    )
    connection.commit()
    connection.close()


def _profile(tmp_path: Path, name: str = "Default") -> tuple[Path, Path]:
    root = tmp_path / "Chrome"
    database = root / name / "Cookies"
    _database(database)
    return root, database


def _allow_macos(monkeypatch: pytest.MonkeyPatch, decryptor: _Decryptor) -> None:
    monkeypatch.setattr(chrome.sys, "platform", "darwin")
    monkeypatch.setattr(chrome, "_pinned_decryptor", lambda *args: decryptor)


def test_extract_selects_and_decrypts_only_requested_provider_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _ = _profile(tmp_path)
    decryptor = _Decryptor()
    _allow_macos(monkeypatch, decryptor)

    jar = chrome.extract_chrome_cookies(
        ("youtube.com", "youtube-nocookie.com"), chrome_root=root
    )

    cookies = {(item.domain, item.name, item.value) for item in jar}
    assert cookies == {
        (".youtube.com", "session", "youtube-value"),
        ("embed.youtube-nocookie.com", "embed", "plain"),
    }
    assert decryptor.values == [b"youtube-encrypted"]


def test_extract_selects_and_decrypts_only_instagram_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _ = _profile(tmp_path)
    decryptor = _Decryptor()
    _allow_macos(monkeypatch, decryptor)

    jar = chrome.extract_chrome_cookies(("instagram.com",), chrome_root=root)

    cookies = {(item.domain, item.name, item.value) for item in jar}
    assert cookies == {(".instagram.com", "sessionid", "instagram-value")}
    assert decryptor.values == [b"instagram-encrypted"]


@pytest.mark.parametrize("profile", ("Default", "Profile 1", "Profile 42"))
def test_extract_accepts_only_named_chrome_profiles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, profile: str
) -> None:
    root, _ = _profile(tmp_path, profile)
    decryptor = _Decryptor()
    _allow_macos(monkeypatch, decryptor)

    assert (
        len(
            chrome.extract_chrome_cookies(
                ("youtube.com", "youtube-nocookie.com"),
                profile,
                chrome_root=root,
            )
        )
        == 2
    )


@pytest.mark.parametrize(
    "profile",
    ("", "Profile", "Profile 0", "../Default", "Default/../Profile 1", "/Default"),
)
def test_extract_rejects_unsafe_profile_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, profile: str
) -> None:
    root, _ = _profile(tmp_path)
    monkeypatch.setattr(chrome.sys, "platform", "darwin")

    with pytest.raises(ValueError, match="unsafe Chrome profile"):
        chrome.extract_chrome_cookies(("youtube.com",), profile, chrome_root=root)


def test_extract_reads_the_network_database_and_legacy_secure_column(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "Chrome"
    database = root / "Default" / "Network" / "Cookies"
    _database(database, secure_column="secure")
    decryptor = _Decryptor()
    _allow_macos(monkeypatch, decryptor)

    assert (
        len(
            chrome.extract_chrome_cookies(
                ("youtube.com", "youtube-nocookie.com"), chrome_root=root
            )
        )
        == 2
    )


def test_extract_converts_chrome_expiry_to_unix_seconds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, database = _profile(tmp_path)
    connection = sqlite3.connect(database)
    chrome_epoch = 11_644_473_600 * 1_000_000
    connection.execute(
        "UPDATE cookies SET expires_utc = ? WHERE name = 'session'",
        (chrome_epoch + 2_000_000_000 * 1_000_000,),
    )
    connection.commit()
    connection.close()
    decryptor = _Decryptor()
    _allow_macos(monkeypatch, decryptor)

    jar = chrome.extract_chrome_cookies(("youtube.com",), chrome_root=root)

    cookie = next(item for item in jar if item.name == "session")
    assert cookie.expires == 2_000_000_000


def test_extract_rejects_a_symlink_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, database = _profile(tmp_path)
    actual = tmp_path / "actual"
    database.replace(actual)
    database.symlink_to(actual)
    monkeypatch.setattr(chrome.sys, "platform", "darwin")

    with pytest.raises(OSError, match="unsafe Chrome Cookie database"):
        chrome.extract_chrome_cookies(("youtube.com",), chrome_root=root)


def test_extract_rejects_a_non_regular_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "Chrome"
    database = root / "Default" / "Cookies"
    database.mkdir(parents=True)
    monkeypatch.setattr(chrome.sys, "platform", "darwin")

    with pytest.raises(OSError, match="unsafe Chrome Cookie database"):
        chrome.extract_chrome_cookies(("youtube.com",), chrome_root=root)


def test_extract_rejects_a_symlink_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _ = _profile(tmp_path, "Profile 1")
    (root / "Default").symlink_to(root / "Profile 1", target_is_directory=True)
    monkeypatch.setattr(chrome.sys, "platform", "darwin")

    with pytest.raises(OSError, match="unsafe Chrome profile"):
        chrome.extract_chrome_cookies(("youtube.com",), chrome_root=root)


def test_extract_reads_the_validated_database_without_a_disk_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, source = _profile(tmp_path)
    decryptor = _Decryptor()
    opened: list[Path] = []
    original = chrome._read_filtered

    def inspect_source(
        database: Path, chrome_root: Path, domains: tuple[str, ...]
    ) -> CookieJar:
        opened.append(database)
        return original(database, chrome_root, domains)

    _allow_macos(monkeypatch, decryptor)
    monkeypatch.setattr(chrome, "_read_filtered", inspect_source)

    chrome.extract_chrome_cookies(
        ("youtube.com", "youtube-nocookie.com"), chrome_root=root
    )

    assert opened == [source]


def test_extract_preserves_an_operating_system_permission_denial(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, database = _profile(tmp_path)
    original_open = chrome.os.open

    def deny_cookie_database(path: object, flags: int, *args: object) -> int:
        if Path(path) == database:
            raise PermissionError("operation not permitted")
        return original_open(path, flags, *args)

    monkeypatch.setattr(chrome.sys, "platform", "darwin")
    monkeypatch.setattr(chrome.os, "open", deny_cookie_database)

    with pytest.raises(PermissionError, match="operation not permitted"):
        chrome.extract_chrome_cookies(("youtube.com",), chrome_root=root)


@pytest.mark.parametrize(
    "domains",
    ((), ("../instagram.com",), ("instagram..com",), ("instagram.com/path",)),
)
def test_extract_rejects_unsafe_domain_allowlists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, domains: tuple[str, ...]
) -> None:
    root, _ = _profile(tmp_path)
    monkeypatch.setattr(chrome.sys, "platform", "darwin")

    with pytest.raises(ValueError, match="domain allowlist"):
        chrome.extract_chrome_cookies(domains, chrome_root=root)


def test_extract_is_macos_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, _ = _profile(tmp_path)
    monkeypatch.setattr(chrome.sys, "platform", "linux")

    with pytest.raises(OSError, match="macOS"):
        chrome.extract_chrome_cookies(("youtube.com",), chrome_root=root)


class _DeniedDecryptor:
    def decrypt(self, value: bytes) -> str | None:
        return None


def test_withheld_keychain_key_is_a_permission_error_not_a_missing_login(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _ = _profile(tmp_path)
    monkeypatch.setattr(chrome.sys, "platform", "darwin")
    monkeypatch.setattr(chrome, "_pinned_decryptor", lambda *args: _DeniedDecryptor())

    with pytest.raises(PermissionError):
        chrome.extract_chrome_cookies(("youtube.com",), chrome_root=root)
    # Plain-text rows alone do not prove the key is available, but no encrypted
    # row also means there is nothing to withhold.
    jar = chrome.extract_chrome_cookies(("youtube-nocookie.com",), chrome_root=root)
    assert {item.name for item in jar} == {"embed"}


def test_profiles_are_listed_with_their_chrome_names(tmp_path: Path) -> None:
    root = tmp_path / "Chrome"
    for name in ("Default", "Profile 2", "System Profile", "Guest Profile"):
        (root / name).mkdir(parents=True)
    (root / "Profile 3").mkdir()
    (root / "Profile 4").symlink_to(root / "Default")
    (root / "Local State").write_text(
        '{"profile": {"info_cache": {"Profile 2": {"name": "Alt"}}}}'
    )

    assert chrome.chrome_profiles(chrome_root=root) == (
        chrome.ChromeProfile("Default", "Default"),
        chrome.ChromeProfile("Profile 2", "Alt"),
        chrome.ChromeProfile("Profile 3", "Profile 3"),
    )
    (root / "Local State").write_text("not json")
    assert [p.display_name for p in chrome.chrome_profiles(chrome_root=root)] == [
        "Default",
        "Profile 2",
        "Profile 3",
    ]
