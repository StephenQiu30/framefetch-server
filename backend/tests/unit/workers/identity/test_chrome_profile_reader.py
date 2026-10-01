"""Fixed Profile, yt-dlp decryption and scoped extraction without secret logging."""

import io
from http.cookiejar import Cookie
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.workers.identity import chrome_profile_reader as reader


def cookie(name="sessionid", value="synthetic", domain=".instagram.com", expires=None):
    return Cookie(
        0,
        name,
        value,
        None,
        False,
        domain,
        True,
        domain.startswith("."),
        "/",
        True,
        True,
        expires,
        False,
        None,
        None,
        {},
    )


@pytest.fixture
def extraction(monkeypatch, tmp_path):
    import yt_dlp.cookies as cookies

    profile = tmp_path / "Default"
    profile.mkdir()
    (profile / "Cookies").touch()
    state = SimpleNamespace(jar=[cookie()], warning=None, error=False)
    original = Mock(side_effect=AssertionError("UI-capable lookup must not run"))
    monkeypatch.setattr(cookies, "_get_mac_keyring_password", original)

    def extract(browser, *, profile, logger):
        assert browser == "chrome"
        assert cookies._get_mac_keyring_password("Chrome", logger) == b"synthetic-key"
        if state.warning:
            logger.warning(state.warning)
        if state.error:
            logger.error("private-value")
        return state.jar

    monkeypatch.setattr(cookies, "extract_cookies_from_browser", extract)
    return state, profile, original


def test_scopes_domains_expiry_and_control_fields_and_restores_library(extraction):
    import yt_dlp.cookies as cookies

    state, profile, original = extraction
    state.jar += [
        cookie("foreign", domain=".evil-instagram.com"),
        cookie("foreign", domain=".google.com"),
        cookie("expired", expires=1),
        cookie("empty", value=""),
        cookie("control", value="unsafe\nvalue"),
    ]
    payload = reader.read_cookies(profile, "instagram", b"synthetic-key")
    assert payload == (
        b"# Netscape HTTP Cookie File\n"
        b".instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tsynthetic\n"
    )
    assert cookies._get_mac_keyring_password is original
    original.assert_not_called()


@pytest.mark.parametrize(
    "warning,error,cause",
    [
        ("failed to decrypt cookie: private-value", False, "cookie_decryption_failed"),
        (None, True, "source_read_failed"),
    ],
)
def test_rejects_decryption_failure_and_partial_material_without_logs(
    extraction, capsys, warning, error, cause
):
    import yt_dlp.cookies as cookies

    state, profile, original = extraction
    state.warning, state.error = warning, error
    with pytest.raises(ValueError, match=cause):
        reader.read_cookies(profile, "instagram", b"synthetic-key")
    assert cookies._get_mac_keyring_password is original
    assert capsys.readouterr() == ("", "")


def test_non_decryption_warning_does_not_reject_valid_material(extraction, capsys):
    state, profile, _ = extraction
    state.warning = "unrelated upstream warning: private-value"
    assert b"sessionid" in reader.read_cookies(profile, "instagram", b"synthetic-key")
    assert capsys.readouterr() == ("", "")


def test_profile_missing_is_explicit(extraction):
    _, profile, _ = extraction
    (profile / "Cookies").unlink()
    with pytest.raises(FileNotFoundError):
        reader.read_cookies(profile, "instagram", b"synthetic-key")


def test_no_current_site_cookies_is_not_login_success(extraction):
    state, profile, _ = extraction
    state.jar = [cookie(domain=".evil.com")]
    with pytest.raises(LookupError, match="site_not_logged_in"):
        reader.read_cookies(profile, "instagram", b"synthetic-key")


@pytest.mark.parametrize(
    "error,exit_code",
    [
        (PermissionError(), 69),
        (FileNotFoundError(), 66),
        (LookupError(), 67),
        (ValueError("cookie_decryption_failed"), 68),
        (ValueError("private-value"), 65),
    ],
)
def test_child_failure_exit_code_is_safe(monkeypatch, capsys, error, exit_code):
    monkeypatch.setattr(
        reader.sys, "argv", ["reader", "--profile", "/fixed", "--site", "instagram"]
    )
    monkeypatch.setattr(
        reader.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"synthetic-key"))
    )
    monkeypatch.setattr(reader, "read_cookies", Mock(side_effect=error))
    assert reader.main() == exit_code
    assert capsys.readouterr() == ("", "")


def test_profile_enumeration_denial_is_not_missing_or_logged_out(
    extraction, monkeypatch
):
    state, profile, original = extraction
    denied = Mock(side_effect=PermissionError(1, "synthetic denial"))
    monkeypatch.setattr(reader.os, "scandir", denied)
    with pytest.raises(PermissionError):
        reader.read_cookies(profile, "instagram", b"synthetic-key")
    denied.assert_called_once_with(profile)
    original.assert_not_called()
