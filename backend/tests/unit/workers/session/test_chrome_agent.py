from http.cookiejar import Cookie

import httpx
import pytest
from app.integrations.site_session_catalog import site_target
from app.workers.session.chrome_agent import (
    COOKIES_PATH,
    ChromeLogin,
    ChromeSourceError,
    CookiesRequest,
    CookiesResponse,
    ExitCode,
    cookies_associated_data,
    create_app,
    headers_associated_data,
)
from app.workers.session.chrome_reader import ChromeProfile
from app.workers.session.page_headers import PageHeadersUnavailable, yuanbao_payload
from app.workers.session.rpc import RpcError, SignedClient
from app.workers.session.sealing import decode, encode, open_sealed, public_key
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

SECRET = b"a" * 32


def cookie(name: str, value: str = "v") -> Cookie:
    return Cookie(
        0,
        name,
        value,
        None,
        False,
        ".youtube.com",
        True,
        True,
        "/",
        True,
        True,
        4_102_444_800,
        False,
        None,
        None,
        {},
    )


class Reader:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, target, profile):
        self.calls.append((target.site, profile))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


async def no_headers(policy, cookies):
    return None


def client_for(reader, profiles=None, clock=lambda: 0.0, header_reader=no_headers):
    app = create_app(
        secret=SECRET,
        profiles=profiles or {},
        reader=reader,
        header_reader=header_reader,
        clock=clock,
    )
    raw = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://a")
    return raw, SignedClient(raw, SECRET)


async def test_reply_is_sealed_to_the_requester_and_cached_briefly():
    login = ChromeLogin(ChromeProfile("Default", "Me"), (cookie("SID"),))
    reader = Reader(login)
    now = [0.0]
    raw, signed = client_for(reader, {"youtube.com": "Default"}, lambda: now[0])
    key = X25519PrivateKey.generate()
    request = CookiesRequest(site="youtube.com", public_key=encode(public_key(key)))
    async with raw:
        reply = await signed.post(COOKIES_PATH, request, CookiesResponse)
        await signed.post(COOKIES_PATH, request, CookiesResponse)
        now[0] = 60.0
        await signed.post(COOKIES_PATH, request, CookiesResponse)
    jar = open_sealed(
        decode(reply.jar), key, associated_data=cookies_associated_data("youtube.com")
    )
    assert b"\tSID\tv" in jar
    assert reply.profile == "Default"
    assert reader.calls == [("youtube.com", "Default")] * 2


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (
            ChromeSourceError(ExitCode.ACTION_REQUIRED, "credential_required", "x"),
            409,
            "credential_required",
        ),
        (
            ChromeSourceError(
                ExitCode.PERMISSION_DENIED, "chrome_permission_required", "x"
            ),
            403,
            "chrome_permission_required",
        ),
        (
            ChromeSourceError(ExitCode.UNAVAILABLE, "chrome_unavailable", "x"),
            503,
            "chrome_unavailable",
        ),
    ],
)
async def test_chrome_failures_keep_a_stable_reason(error, status, code):
    raw, signed = client_for(Reader(error))
    key = encode(public_key(X25519PrivateKey.generate()))
    async with raw:
        with pytest.raises(RpcError) as caught:
            await signed.post(
                COOKIES_PATH,
                CookiesRequest(site="youtube.com", public_key=key),
                CookiesResponse,
            )
        assert (caught.value.status, caught.value.code) == (status, code)
        assert (await raw.post(COOKIES_PATH, json={})).status_code == 401


def test_site_target_used_by_agent_covers_youtube_domains():
    assert "youtube.com" in site_target("youtube.com").cookie_domains


async def test_page_headers_are_sealed_separately_and_only_on_request():
    login = ChromeLogin(ChromeProfile("Default", "Me"), (cookie("hy_user"),))
    calls = []

    async def header_reader(policy, cookies):
        calls.append(policy.site)
        return b'{"userId":"u","token":"t","headers":{"X-HY92":"s"}}'

    raw, signed = client_for(Reader(login), header_reader=header_reader)
    key = X25519PrivateKey.generate()
    encoded = encode(public_key(key))
    async with raw:
        status = await signed.post(
            COOKIES_PATH,
            CookiesRequest(site="weixin.qq.com", public_key=encoded),
            CookiesResponse,
        )
        lease = await signed.post(
            COOKIES_PATH,
            CookiesRequest(
                site="weixin.qq.com", public_key=encoded, include_headers=True
            ),
            CookiesResponse,
        )
    assert status.headers is None
    assert calls == ["weixin.qq.com"]
    opened = open_sealed(
        decode(lease.headers),
        key,
        associated_data=headers_associated_data("weixin.qq.com"),
    )
    assert b"X-HY92" in opened


async def test_page_without_identity_is_a_login_problem():
    login = ChromeLogin(ChromeProfile("Default", "Me"), (cookie("hy_user"),))

    async def header_reader(policy, cookies):
        raise PageHeadersUnavailable("no identity")

    raw, signed = client_for(Reader(login), header_reader=header_reader)
    key = encode(public_key(X25519PrivateKey.generate()))
    async with raw:
        with pytest.raises(RpcError) as caught:
            await signed.post(
                COOKIES_PATH,
                CookiesRequest(
                    site="weixin.qq.com", public_key=key, include_headers=True
                ),
                CookiesResponse,
            )
    assert (caught.value.status, caught.value.code) == (409, "credential_required")


def test_yuanbao_identity_falls_back_to_login_cookies():
    payload = yuanbao_payload(
        {"userId": "", "token": "", "headers": {"X-HY92": "s"}},
        (cookie("hy_user", "u1"), cookie("hy_token", "t1")),
    )
    assert b'"userId":"u1"' in payload and b'"token":"t1"' in payload
    with pytest.raises(PageHeadersUnavailable):
        yuanbao_payload({"headers": {"X-HY92": "s"}}, ())
