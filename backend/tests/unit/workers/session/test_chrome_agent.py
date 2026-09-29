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
)
from app.workers.session.chrome_reader import ChromeProfile
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


def client_for(reader, profiles=None, clock=lambda: 0.0):
    app = create_app(secret=SECRET, profiles=profiles or {}, reader=reader, clock=clock)
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
