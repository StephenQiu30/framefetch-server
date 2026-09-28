from __future__ import annotations

import time
from http.cookiejar import Cookie, CookieJar
from pathlib import Path

import pytest
from app.integrations.site_session_catalog import site_target_for_host
from app.workers.session import seed
from app.workers.session.chrome_reader import ChromeProfile
from app.workers.session.seed import ExitCode, SeedError, select_seed

NOW = time.time()
YOUTUBE = site_target_for_host("youtube.com")
LOGIN = {"SAPISID": "a", "__Secure-3PSID": "b"}


def cookie(name: str, value: str, *, domain=".youtube.com", expires=NOW + 3600):
    return Cookie(
        0,
        name,
        value,
        None,
        False,
        domain,
        True,
        True,
        "/",
        True,
        True,
        None if expires is None else int(expires),
        expires is None,
        None,
        None,
        {},
        False,
    )


def jar(*cookies: Cookie) -> CookieJar:
    result = CookieJar()
    for item in cookies:
        result.set_cookie(item)
    return result


def profiles(monkeypatch, *names: str) -> None:
    monkeypatch.setattr(
        seed,
        "chrome_profiles",
        lambda **_: tuple(ChromeProfile(n, f"name-{n}") for n in names),
    )


def extractor(by_profile: dict[str, CookieJar | type[Exception]]):
    calls: list[tuple] = []

    def extract(domains, profile, *, chrome_root):
        calls.append((domains, profile))
        value = by_profile[profile]
        if isinstance(value, type):
            raise value("boom")
        return value

    extract.calls = calls  # type: ignore[attr-defined]
    return extract


def logged_in() -> CookieJar:
    return jar(*(cookie(n, v) for n, v in LOGIN.items()), cookie("PREF", "x"))


def test_single_logged_in_profile_is_selected_with_only_live_site_cookies(monkeypatch):
    profiles(monkeypatch, "Default", "Profile 2")
    session = logged_in()
    session.set_cookie(cookie("OLD", "x", expires=NOW - 1))
    session.set_cookie(cookie("EMPTY", ""))
    session.set_cookie(cookie("SID", "evil", domain="youtube.com.attacker.test"))
    extract = extractor({"Default": jar(cookie("PREF", "x")), "Profile 2": session})

    choice = select_seed(YOUTUBE, extract=extract, now=NOW)

    assert choice.profile.directory == "Profile 2"
    assert {c.name for c in choice.cookies} == {"SAPISID", "__Secure-3PSID", "PREF"}
    assert extract.calls[0][0] == ("youtube-nocookie.com", "youtube.com")


def test_two_logged_in_profiles_require_an_explicit_choice(monkeypatch):
    profiles(monkeypatch, "Default", "Profile 2")
    extract = extractor({"Default": logged_in(), "Profile 2": logged_in()})
    with pytest.raises(SeedError) as error:
        select_seed(YOUTUBE, extract=extract, now=NOW)
    assert error.value.code is ExitCode.ACTION_REQUIRED
    assert "Default（name-Default）" in str(error.value)
    choice = select_seed(YOUTUBE, profile="Default", extract=extract, now=NOW)
    assert choice.profile.directory == "Default"


@pytest.mark.parametrize(
    ("by_profile", "code"),
    [
        ({"Default": jar(cookie("PREF", "x"))}, ExitCode.ACTION_REQUIRED),
        ({"Default": FileNotFoundError}, ExitCode.ACTION_REQUIRED),
        ({"Default": PermissionError}, ExitCode.PERMISSION_DENIED),
        ({"Default": OSError}, ExitCode.UNAVAILABLE),
        # Session-only cookies disappear when Chrome restarts; not a durable login.
        (
            {"Default": jar(*(cookie(n, v, expires=None) for n, v in LOGIN.items()))},
            ExitCode.ACTION_REQUIRED,
        ),
    ],
)
def test_no_usable_login_is_reported_precisely(monkeypatch, by_profile, code):
    profiles(monkeypatch, "Default")
    with pytest.raises(SeedError) as error:
        select_seed(YOUTUBE, extract=extractor(by_profile), now=NOW)
    assert error.value.code is code


def test_denied_profile_blocks_a_guess_even_if_another_is_logged_in(monkeypatch):
    profiles(monkeypatch, "Default", "Profile 2")
    extract = extractor({"Default": PermissionError, "Profile 2": logged_in()})
    with pytest.raises(SeedError) as error:
        select_seed(YOUTUBE, extract=extract, now=NOW)
    assert error.value.code is ExitCode.PERMISSION_DENIED


def test_unknown_profile_and_missing_chrome(monkeypatch, tmp_path: Path):
    profiles(monkeypatch, "Default")
    with pytest.raises(SeedError, match="Profile 9"):
        select_seed(YOUTUBE, profile="Profile 9", extract=extractor({}), now=NOW)
    monkeypatch.undo()
    with pytest.raises(SeedError) as error:
        select_seed(YOUTUBE, chrome_root=tmp_path / "missing", now=NOW)
    assert error.value.code is ExitCode.ACTION_REQUIRED


def test_unknown_site_accepts_any_persistent_cookie(monkeypatch):
    target = site_target_for_host("media.example.co.uk")
    profiles(monkeypatch, "Default")
    extract = extractor(
        {"Default": jar(cookie("sid", "1", domain=".example.co.uk"), cookie("x", "2"))}
    )
    choice = select_seed(target, extract=extract, now=NOW)
    assert [c.name for c in choice.cookies] == ["sid"]
    assert extract.calls[0][0] == ("example.co.uk",)


def test_invalid_site_is_rejected_before_reading_chrome(capsys):
    assert seed.main(["import", "--site", "10.0.0.1"]) == ExitCode.ACTION_REQUIRED
    assert "不能为「10.0.0.1」登记会话" in capsys.readouterr().err


def test_settings_come_from_the_env_file_and_process(tmp_path: Path, monkeypatch):
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    env = tmp_path / ".env"
    env.write_text(
        "DATABASE_URL=postgresql+asyncpg://a:b@db:5432/video\n"
        f"SITE_SESSION_ENCRYPTION_KEY={key}\nUNRELATED=1\n"
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://a:b@override:5432/video")
    settings = seed.load_settings(env)
    assert settings.database_url.endswith("@override:5432/video")
    assert settings.site_session_encryption_key.get_secret_value() == key
