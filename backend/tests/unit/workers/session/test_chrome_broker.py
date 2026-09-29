import pytest
from app.workers.session.chrome_agent import (
    CookiesResponse,
    cookies_associated_data,
    headers_associated_data,
)
from app.workers.session.chrome_broker import (
    LIVE_REVISION,
    ChromeSessionBroker,
    SessionLoginRequired,
    SessionNotReady,
)
from app.workers.session.contracts import lease_associated_data
from app.workers.session.rpc import RpcError
from app.workers.session.sealing import (
    decode_public_key,
    encode,
    open_sealed,
    public_key,
    seal,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

JARS = {
    "youtube.com": b".youtube.com\tTRUE\t/\tTRUE\t4102444800\tSID\tvalue\n",
    "weixin.qq.com": (b".yuanbao.tencent.com\tTRUE\t/\tTRUE\t4102444800\thy_user\tu\n"),
}
JAR = b"# Netscape HTTP Cookie File\n" + JARS["youtube.com"]


class Agent:
    def __init__(self, error: RpcError | None = None) -> None:
        self.error = error

    async def post(self, path, body, response):
        if self.error is not None:
            raise self.error
        recipient = decode_public_key(body.public_key)
        jar = b"# Netscape HTTP Cookie File\n" + JARS[body.site]
        sealed = seal(
            jar, recipient, associated_data=cookies_associated_data(body.site)
        )
        headers = None
        if body.include_headers and body.site == "weixin.qq.com":
            headers = encode(
                seal(
                    b'{"headers":{}}',
                    recipient,
                    associated_data=headers_associated_data(body.site),
                )
            )
        return CookiesResponse(
            site=body.site, profile="Default", jar=encode(sealed), headers=headers
        )


async def test_lease_reseals_live_chrome_cookies_for_the_runner():
    broker = ChromeSessionBroker(Agent(), lease_seconds=600)
    runner = X25519PrivateKey.generate()
    assert await broker.ready_revision("youtube.com") == LIVE_REVISION
    grant = await broker.lease(
        task_id="t1",
        site="youtube.com",
        seed_revision=LIVE_REVISION,
        runner_key=public_key(runner),
    )
    jar = open_sealed(
        grant.jar,
        runner,
        associated_data=lease_associated_data(
            "jar", "t1", "youtube.com", LIVE_REVISION, grant.expires_at
        ),
    )
    assert jar == JAR
    assert grant.headers is None


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("credential_required", SessionLoginRequired),
        ("chrome_profile_ambiguous", SessionLoginRequired),
        ("chrome_permission_required", SessionNotReady),
        ("rpc_unavailable", SessionNotReady),
    ],
)
async def test_agent_failures_split_login_from_transient(code, expected):
    broker = ChromeSessionBroker(Agent(RpcError(code, 409)), lease_seconds=600)
    with pytest.raises(expected):
        await broker.ready_revision("youtube.com")


async def test_stale_revision_is_rejected():
    broker = ChromeSessionBroker(Agent(), lease_seconds=600)
    with pytest.raises(SessionNotReady):
        await broker.lease(
            task_id="t1",
            site="youtube.com",
            seed_revision=7,
            runner_key=public_key(X25519PrivateKey.generate()),
        )


async def test_page_headers_are_resealed_as_a_separate_lease_part():
    broker = ChromeSessionBroker(Agent(), lease_seconds=600)
    runner = X25519PrivateKey.generate()
    grant = await broker.lease(
        task_id="t2",
        site="weixin.qq.com",
        seed_revision=LIVE_REVISION,
        runner_key=public_key(runner),
    )
    assert grant.headers is not None
    headers = open_sealed(
        grant.headers,
        runner,
        associated_data=lease_associated_data(
            "headers", "t2", "weixin.qq.com", LIVE_REVISION, grant.expires_at
        ),
    )
    assert headers == b'{"headers":{}}'
