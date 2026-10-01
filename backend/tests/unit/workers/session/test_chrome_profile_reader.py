"""Synthetic extraction verifies scope and output; no browser files are read."""

import sys
from http.cookiejar import Cookie
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.workers.session import chrome_profile_reader as reader
from app.workers.session.macos_keychain import KeychainUnavailable


def cookie(name="SID", value="synthetic", domain=".youtube.com", expires=None):
    return Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=True,
        domain_initial_dot=domain.startswith("."),
        path="/",
        path_specified=True,
        secure=True,
        expires=expires,
        discard=False,
        comment=None,
        comment_url=None,
        rest={},
    )


@pytest.fixture
def extractor(monkeypatch):
    import yt_dlp.cookies as cookies

    calls = []
    state = SimpleNamespace(jar=[cookie()], warning=False, error=False)

    def extract(browser, *, profile, logger):
        calls.append((browser, profile))
        assert cookies._get_mac_keyring_password("Chrome", logger) == b"synthetic-key"
        if state.warning:
            logger.warning("synthetic extraction warning with private-value")
        if state.error:
            logger.error("synthetic extraction error with private-value")
        return state.jar

    monkeypatch.setattr(cookies, "extract_cookies_from_browser", extract)
    # read_cookies replaces this private lookup inside its child. Restore the
    # real library function after the synthetic test rather than leaking it.
    monkeypatch.setattr(cookies, "_get_mac_keyring_password", lambda *_: b"fixture")
    monkeypatch.setattr(reader, "chrome_storage_password", lambda: b"synthetic-key")
    return state, calls


def test_fixed_profile_scopes_current_cookie_material_without_platform_calls(extractor):
    state, calls = extractor
    state.jar = [
        cookie(),
        cookie("foreign", "must-not-export", ".google.com"),
        cookie("foreign", "must-not-export", ".evil-youtube.com"),
        cookie("expired", expires=1),
        cookie("empty", value=""),
        cookie("control", value="unsafe\nvalue"),
    ]
    payload = reader.read_cookies(Path("/fixed/Default"), "youtube")
    assert calls == [("chrome", "/fixed/Default")]
    assert payload == (
        b"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tsynthetic\n"
    )


def test_keychain_refusal_never_calls_extractor(extractor, monkeypatch):
    _, calls = extractor

    def denied():
        raise KeychainUnavailable()

    monkeypatch.setattr(reader, "chrome_storage_password", denied)
    with pytest.raises(KeychainUnavailable):
        reader.read_cookies(Path("/fixed/Default"), "youtube")
    assert calls == []


def test_extraction_warning_allows_complete_target_material_without_logging_values(
    extractor, capsys
):
    state, _ = extractor
    state.warning = True
    payload = reader.read_cookies(Path("/fixed/Default"), "youtube")
    assert b"SID\tsynthetic\n" in payload
    assert capsys.readouterr() == ("", "")


def test_extraction_error_rejects_even_complete_target_material_without_logging_values(
    extractor, capsys
):
    state, _ = extractor
    state.error = True
    with pytest.raises(ValueError, match="source_read_failed"):
        reader.read_cookies(Path("/fixed/Default"), "youtube")
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (KeychainUnavailable(-25293), 77),
        (KeychainUnavailable(-25308), 77),
        (KeychainUnavailable(-25300), 65),
        (KeychainUnavailable(), 65),
        (FileNotFoundError("synthetic-private-path"), 66),
        (LookupError("synthetic-private-value"), 67),
        (ValueError("synthetic-private-value"), 65),
    ],
)
def test_reader_exit_codes_never_write_material_for_failures(
    error, expected, monkeypatch, capsys
):
    monkeypatch.setattr(
        sys, "argv", ["reader", "--profile", "/fixed/Default", "--site", "youtube"]
    )

    def failed(*_):
        raise error

    monkeypatch.setattr(reader, "read_cookies", failed)
    assert reader.main() == expected
    assert capsys.readouterr() == ("", "")


def test_reader_stdout_is_only_site_material_and_no_key(monkeypatch, capsysbinary):
    monkeypatch.setattr(
        sys, "argv", ["reader", "--profile", "/fixed/Default", "--site", "youtube"]
    )
    monkeypatch.setattr(reader, "read_cookies", lambda *_: b"synthetic-site-material")
    assert reader.main() == 0
    assert capsysbinary.readouterr() == (b"synthetic-site-material", b"")
