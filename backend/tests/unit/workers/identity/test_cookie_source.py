"""Bearer refusal, current lock preflight, cache and stable account digest."""

import base64
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from app.core.config import CookieSourceSettings
from app.workers.identity import cookie_source as module
from app.workers.identity.keychain import KeychainUnavailable
from pydantic import SecretStr

TOKEN = "unit-test-only-identity-token-32-bytes"
COOKIES = (
    b"# Netscape HTTP Cookie File\n"
    b".instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tsynthetic\n"
)


def request(site="instagram", seconds=30):
    return module.CookieRequest(
        site=site,
        task_id="task-id",
        deadline=datetime.now(UTC) + timedelta(seconds=seconds),
    )


@pytest.fixture
def source(tmp_path, monkeypatch):
    settings = CookieSourceSettings(
        cookie_source_token=SecretStr(TOKEN), cookie_source_chrome_profile=tmp_path
    )
    source = module.CookieSource(settings)
    preflight = Mock()
    read = Mock(return_value=(b"synthetic-key", {"graphic_access": True}))
    monkeypatch.setattr(module, "require_unlocked", preflight)
    monkeypatch.setattr(module, "storage_password", read)
    monkeypatch.setattr(
        module, "validate_storage_acl", Mock(return_value={"acl_valid": True})
    )
    source._extract = AsyncMock(return_value=COOKIES)
    return source, preflight, read


async def test_each_cache_hit_still_checks_lock_and_lock_failure_never_extracts(source):
    service, preflight, read = source
    first = await service.cookies(request())
    second = await service.cookies(request())
    assert first == second and base64.b64decode(first["cookies"]) == COOKIES
    assert preflight.call_count == 2 and read.call_count == 1
    preflight.side_effect = KeychainUnavailable("keychain_locked")
    with pytest.raises(KeychainUnavailable, match="keychain_locked"):
        await service.cookies(request())
    assert service._extract.await_count == 2 and read.call_count == 1


async def test_cached_decryption_failure_refreshes_key_once_with_new_precheck(source):
    service, preflight, read = source
    service._password = b"old-synthetic-key"
    service._extract.side_effect = [None, COOKIES]
    assert (await service.cookies(request()))["digest"]
    assert read.call_count == 1 and preflight.call_count == 2


async def test_repeat_decryption_failure_is_terminal(source):
    service, preflight, read = source
    service._extract.return_value = None
    with pytest.raises(KeychainUnavailable, match="cookie_decryption_failed"):
        await service.cookies(request())
    assert read.call_count == 2 and preflight.call_count == 2
    assert service._password is None


async def test_denied_key_read_never_extracts_and_does_not_retry(source):
    service, _, read = source
    read.side_effect = KeychainUnavailable("keychain_read_denied")
    with pytest.raises(KeychainUnavailable, match="keychain_read_denied"):
        await service.cookies(request())
    service._extract.assert_not_called()
    assert read.call_count == 1


async def test_digest_ignores_cookie_order_expiry_renewal_and_visitor_values(source):
    service, _, _ = source
    first = await service.cookies(request())
    service._extract.return_value = COOKIES + (
        b".instagram.com\tTRUE\t/\tTRUE\t0\tvisitor\tchanging-analytics\n"
    )
    second = await service.cookies(request())
    assert first["digest"] == second["digest"]
    service._extract.return_value = COOKIES.replace(b"synthetic", b"different-account")
    assert (await service.cookies(request()))["digest"] != first["digest"]


@pytest.mark.parametrize(
    "payload,cause",
    [
        (COOKIES.replace(b"sessionid", b"visitor"), "site_not_logged_in"),
        (COOKIES.replace(b"\t0\t", b"\t1\t"), "cookie_expired"),
    ],
)
async def test_guest_only_or_expired_material_is_not_login_success(
    source, payload, cause
):
    service, _, _ = source
    service._extract.return_value = payload
    with pytest.raises(KeychainUnavailable, match=cause):
        await service.cookies(request())


async def test_qq_requires_both_account_cookies_and_salts_site(source):
    service, _, _ = source
    service._extract.return_value = (
        b"# Netscape HTTP Cookie File\n"
        b".v.qq.com\tTRUE\t/\tTRUE\t0\tv_vuserid\tsynthetic-user\n"
        b".v.qq.com\tTRUE\t/\tTRUE\t0\tv_vusession\tsynthetic-session\n"
    )
    result = await service.cookies(request("qqvideo"))
    assert len(result["digest"]) == 64
    service._extract.return_value = (
        b"\n".join(service._extract.return_value.splitlines()[:2]) + b"\n"
    )
    with pytest.raises(KeychainUnavailable, match="site_not_logged_in"):
        await service.cookies(request("qqvideo"))


@pytest.mark.parametrize(
    "site,cause",
    [
        ("tiktok", "identity_not_declared"),
        ("youtube", "identity_cookie_rules_unverified"),
    ],
)
async def test_unverified_cookie_rules_and_none_never_read_key(source, site, cause):
    service, _, read = source
    with pytest.raises(KeychainUnavailable, match=cause):
        await service.cookies(request(site))
    read.assert_not_called()


@pytest.mark.parametrize("seconds", [0, -1])
async def test_deadline_refusal_never_accesses_host(source, seconds):
    service, preflight, read = source
    with pytest.raises(KeychainUnavailable, match="identity_deadline_invalid"):
        await service.cookies(request(seconds=seconds))
    preflight.assert_not_called()
    read.assert_not_called()


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Basic arbitrary"])
async def test_unauthenticated_requests_return_401_before_parsing_or_host_access(
    source, authorization
):
    service, preflight, _ = source
    app = module.create_app(service.settings)
    app.state.cookie_source._extract = AsyncMock(side_effect=AssertionError())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://host"
    ) as client:
        response = await client.post(
            "/cookies",
            content=b"not-json",
            headers={"Authorization": authorization} if authorization else {},
        )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    preflight.assert_not_called()
    assert "cookies" not in response.json()


async def test_authenticated_payload_is_bounded_and_errors_never_echo_input(source):
    service, _, _ = source
    app = module.create_app(service.settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://host",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as client:
        response = await client.post("/cookies", content=b"x" * 4097)
        assert response.status_code == 413
        response = await client.post("/cookies", json={"site": "private-value"})
        assert response.status_code == 422
        assert "private-value" not in response.text
        assert response.headers["cache-control"] == "no-store"


async def test_authenticated_success_and_lock_failure(source, monkeypatch):
    service, preflight, _ = source
    monkeypatch.setattr(module, "CookieSource", lambda _: service)
    app = module.create_app(service.settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://host",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as client:
        response = await client.post("/cookies", json=request().model_dump(mode="json"))
        assert response.status_code == 200
        preflight.side_effect = KeychainUnavailable("keychain_locked")
        response = await client.post("/cookies", json=request().model_dump(mode="json"))
        assert response.status_code == 503
        assert response.json() == {"cause": "keychain_locked"}


async def test_download_deadline_does_not_reset_or_reduce_shared_budget(source):
    service, _, _ = source
    value = request(seconds=7000)
    await service.cookies(value)
    assert service._extract.call_args.args[0].deadline == value.deadline


async def test_extractor_cancellation_kills_group_and_waits_for_exit(
    source, monkeypatch
):
    import asyncio

    service, _, _ = source
    started = asyncio.Event()

    async def communicate(password):
        assert password == b"synthetic-key"
        started.set()
        await asyncio.Future()

    process = Mock(pid=123, returncode=None)
    process.communicate = communicate

    async def wait():
        process.returncode = -9
        return -9

    process.wait = AsyncMock(side_effect=wait)
    monkeypatch.setattr(
        module.asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
    )
    kill = Mock()
    monkeypatch.setattr(module.os, "killpg", kill)
    service._password = b"synthetic-key"
    task = asyncio.create_task(module.CookieSource._extract(service, request()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    kill.assert_called_once_with(123, module.signal.SIGKILL)
    process.wait.assert_awaited_once()


async def test_acl_failure_disables_service_and_releases_cache(source, monkeypatch):
    service, _, read = source
    acl = Mock(side_effect=KeychainUnavailable("keychain_acl_invalid"))
    monkeypatch.setattr(module, "validate_storage_acl", acl)
    with pytest.raises(KeychainUnavailable, match="keychain_acl_invalid"):
        await service.cookies(request())
    with pytest.raises(KeychainUnavailable, match="keychain_acl_disabled"):
        await service.cookies(request())
    assert service._password is None and acl.call_count == 1
    read.assert_not_called()
    service._extract.assert_not_called()


async def test_startup_acl_and_every_secret_refresh_are_validated(source, monkeypatch):
    service, preflight, read = source
    acl = Mock(return_value={"acl_valid": True})
    monkeypatch.setattr(module, "validate_storage_acl", acl)
    await service.start()
    await service.cookies(request())
    await service.cookies(request())
    assert acl.call_count == 2 and read.call_count == 1
    service._extract.side_effect = [None, COOKIES]
    await service.cookies(request())
    assert acl.call_count == 3 and read.call_count == 2
    assert preflight.call_count == 5


async def test_lifespan_releases_password_even_after_failure(source, monkeypatch):
    service, _, _ = source
    monkeypatch.setattr(module, "CookieSource", lambda _: service)
    app = module.create_app(service.settings)
    with pytest.raises(RuntimeError):
        async with app.router.lifespan_context(app):
            await service.cookies(request())
            assert service._password
            raise RuntimeError("synthetic")
    assert service._password is None


async def test_locked_startup_never_dumps_acl_or_reads_security(source, monkeypatch):
    service, preflight, read = source
    preflight.side_effect = KeychainUnavailable("keychain_locked")
    acl = Mock()
    monkeypatch.setattr(module, "validate_storage_acl", acl)
    await service.start()
    with pytest.raises(KeychainUnavailable, match="keychain_locked"):
        await service.cookies(request())
    acl.assert_not_called()
    read.assert_not_called()


def test_acl_consuming_deadline_never_reads_secret(source, monkeypatch):
    service, _, read = source
    value = request(seconds=1)
    clock = Mock()
    clock.now.side_effect = [value.deadline - timedelta(seconds=1), value.deadline]
    monkeypatch.setattr(module, "datetime", clock)
    monkeypatch.setattr(
        module, "validate_storage_acl", Mock(return_value={"acl_valid": True})
    )
    with pytest.raises(KeychainUnavailable, match="identity_deadline_invalid"):
        service._read_password(value.deadline)
    read.assert_not_called()


async def test_unreadable_profile_has_explicit_safe_cause(source, monkeypatch):
    service, _, _ = source
    process = Mock(pid=123, returncode=69)
    process.communicate = AsyncMock(return_value=(b"", None))
    monkeypatch.setattr(
        module.asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
    )
    with pytest.raises(KeychainUnavailable, match="chrome_profile_unreadable"):
        await module.CookieSource._extract(service, request())
