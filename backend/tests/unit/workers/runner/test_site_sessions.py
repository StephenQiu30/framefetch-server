"""Exercise encrypted broker leases through the Runner's operation boundary."""

import time

import httpx
import pytest
from app.services.provider_types import ProviderAccessMode
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_credential_lease import ProviderCredentialLocks
from app.workers.runner.provider_registry import provider_profile
from app.workers.runner.provider_sessions import ProviderSessionStore
from app.workers.runner.settings import RunnerSettings
from app.workers.runner.site_sessions import SiteSessionClient
from app.workers.session.contracts import (
    LEASE_PATH,
    STATUS_PATH,
    LeaseRequest,
    LeaseResponse,
    StatusResponse,
    lease_associated_data,
)
from app.workers.session.rpc import SignedClient
from app.workers.session.sealing import decode_public_key, encode, seal

SECRET = b"s" * 32
URL = "https://www.youtube.com/watch?v=owned"
COOKIE = (
    b"# Netscape HTTP Cookie File\n"
    b".youtube.com\tTRUE\t/\tTRUE\t4102444800\tSID\tfixture\n"
)


@pytest.fixture
async def leased_store(tmp_path):
    requests = []

    async def broker(request):
        requests.append(request.url.path)
        if request.url.path == STATUS_PATH:
            response = StatusResponse(site="youtube.com", source_generation=1)
        elif request.url.path == LEASE_PATH:
            body = LeaseRequest.model_validate_json(request.content)
            expires_at = int(time.time()) + 600
            jar = seal(
                COOKIE,
                decode_public_key(body.public_key),
                associated_data=lease_associated_data(
                    "jar", body.task_id, body.site, body.source_generation, expires_at
                ),
            )
            response = LeaseResponse(
                site=body.site,
                source_generation=body.source_generation,
                expires_at=expires_at,
                jar=encode(jar),
            )
        else:
            raise httpx.ConnectError("broker is unavailable after granting the lease")
        return httpx.Response(200, json=response.model_dump())

    settings = RunnerSettings(
        runner_hmac_secret=SECRET.decode(),
        runner_egress_proxy="http://egress-proxy:3128",
        runner_workspace_root=tmp_path / "work",
        runner_access_mode="operator_managed",
        runner_provider_session_temp_root=tmp_path / "sessions",
        runner_session_broker_url="http://broker",
        runner_session_rpc_secret=SECRET.decode(),
    )
    client = SiteSessionClient("http://broker", SECRET)
    await client.close()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(broker), base_url="http://broker"
    )
    client._client = SignedClient(client._http, SECRET)
    store = ProviderSessionStore(
        settings,
        site_sessions=client,
        credential_locks=ProviderCredentialLocks(),
        enforce_memory_backing=False,
    )
    try:
        yield store, requests
    finally:
        await store.close()


async def test_operation_finishes_without_contacting_broker_after_lease(leased_store):
    store, requests = leased_store
    context = await store.context_for(
        provider_profile(URL), url=URL, access_mode=ProviderAccessMode.OPERATOR_MANAGED
    )
    async with store.operation(context) as jar:
        assert jar.read_bytes() == COOKIE
        # yt-dlp may update its working jar. This must not add a second
        # network dependency after successful media processing.
        jar.write_bytes(
            COOKIE + b".youtube.com\tTRUE\t/\tTRUE\t4102444800\tPREF\tupdated\n"
        )
        temporary_directory = jar.parent
    assert not temporary_directory.exists()
    assert requests == [STATUS_PATH, LEASE_PATH]


async def test_operation_preserves_failure_and_cleans_material(leased_store):
    store, requests = leased_store
    context = await store.context_for(
        provider_profile(URL), url=URL, access_mode=ProviderAccessMode.OPERATOR_MANAGED
    )
    failure = RunnerFailure("egress_challenged", status=409)
    with pytest.raises(RunnerFailure) as caught:
        async with store.operation(context) as jar:
            temporary_directory = jar.parent
            raise failure
    assert caught.value is failure
    assert not temporary_directory.exists()
    assert requests == [STATUS_PATH, LEASE_PATH]
