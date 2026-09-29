from __future__ import annotations

from http.cookiejar import Cookie

import pytest
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.netscape_cookie import (
    has_safe_cookie_fields,
    is_allowed_domain,
    parse_cookie_payload,
    serialize_cookies,
)

COOKIE = (
    b"# Netscape HTTP Cookie File\n"
    b"# an operator comment\n"
    b"#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tfixture\n"
    b"youtube.com\tFALSE\t/\tTRUE\t1\told\tstale\n"
)


@pytest.mark.parametrize(
    "payload",
    [
        COOKIE.replace(b"fixture", b"fi\x00xture"),
        COOKIE.replace(b"youtube.com", b"example.com"),
        COOKIE.replace(b"TRUE\t2147483647", b"invalid\t2147483647"),
    ],
)
def test_parse_rejects_unsafe_or_cross_provider_payloads(payload: bytes) -> None:
    with pytest.raises(RunnerFailure) as caught:
        parse_cookie_payload(payload, frozenset({"youtube.com"}))
    assert caught.value.code == "credential_rejected"


def test_domain_allowlist_accepts_subdomains_but_not_suffix_collisions() -> None:
    assert is_allowed_domain(".youtube.com", ("youtube.com",))
    assert is_allowed_domain("accounts.youtube.com", ("youtube.com",))
    assert not is_allowed_domain("notyoutube.com", ("youtube.com",))


def test_serializer_preserves_netscape_shape_and_http_only_marker() -> None:
    cookie = Cookie(
        version=0,
        name="SID",
        value="fixture",
        port=None,
        port_specified=False,
        domain=".youtube.com",
        domain_specified=True,
        domain_initial_dot=True,
        path="/",
        path_specified=True,
        secure=True,
        expires=2147483647,
        discard=False,
        comment=None,
        comment_url=None,
        rest={"HttpOnly": None},
        rfc2109=False,
    )

    assert serialize_cookies((cookie,)) == (
        b"# Netscape HTTP Cookie File\n"
        b"#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tfixture\n"
    )
    cookie.value = "fi\x00xture"
    assert not has_safe_cookie_fields(cookie)


def test_parse_rejects_mixed_cookie_domains() -> None:
    payload = (
        b"# Netscape HTTP Cookie File\n"
        b".douyin.com\tTRUE\t/\tTRUE\t0\tsessionid\tfixture\n"
        b"aweme.snssdk.com\tFALSE\t/\tTRUE\t0\tresponse\tfixture\n"
    )
    with pytest.raises(RunnerFailure) as caught:
        parse_cookie_payload(payload, frozenset({"douyin.com"}))
    assert caught.value.code == "credential_rejected"
