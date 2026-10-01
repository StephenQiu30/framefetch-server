import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from app.api.deps import get_current_user
from app.core.config import Settings
from app.core.security.url_cipher import URLCipher
from app.integrations.url_security import FernetUrlEnvelope, MediaUrlValidator
from app.main import create_app
from app.models import MediaInspectionRow, OutboxEventRow, ResourceAdmissionRow
from app.repositories.downloads.intent_repository import IntentRepository
from app.repositories.downloads.repository import SqlAlchemyDownloadRepository
from app.services.downloads.errors import (
    MediaInspectionFailure,
)
from app.services.downloads.fingerprints import HmacRequestFingerprinter
from app.services.downloads.inspect_media import InspectMedia
from app.services.downloads.intents import IntentService
from app.services.provider_failures import ProviderFailure
from app.services.quotas import UserQuota
from app.workers.download.activities import InspectionActivities
from app.workers.download.workflows import InspectionCommand
from cryptography.fernet import Fernet
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.integration.api.test_download_routes import TEST_USER
from tests.unit.services.fakes import FakeRunner
from tests.unit.services.test_inspect_media import runner_result

NOW = datetime(2026, 9, 22, tzinfo=UTC)
URL = "https://www.youtube.com/watch?v=BaW_jenozKc"


def components(engine, runner=None):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repo = IntentRepository(sessions)
    cipher = FernetUrlEnvelope(URLCipher(Fernet.generate_key()), key_id="test")
    fingerprint = HmacRequestFingerprinter(b"f" * 32)
    clock = [NOW]

    service = IntentService(
        repo,
        MediaUrlValidator(),
        cipher,
        fingerprint,
        now=lambda: clock[0],
        new_id=uuid4,
    )
    inspector = InspectMedia(
        repository=SqlAlchemyDownloadRepository(sessions),
        runner=runner or FakeRunner(runner_result()),
        url_validator=MediaUrlValidator(),
        url_cipher=cipher,
        fingerprinter=fingerprint,
        now=lambda: clock[0],
        new_id=uuid4,
        inspection_ttl=timedelta(minutes=15),
        max_duration_seconds=3600,
    )
    executor = InspectionActivities(
        repo,
        inspector,
        cipher,
        clock=lambda: clock[0],
    )
    return service, repo, executor, clock, sessions


async def test_api_accepts_before_parse_and_recovers_same_result(postgres_engine):
    service, repo, executor, _, sessions = components(postgres_engine)
    app = create_app(Settings(app_env="test"))
    app.state.services.intent_service = service
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            "/api/download-intents",
            json={"input": f"分享视频 {URL}"},
            headers={"Idempotency-Key": "same"},
        )
        assert created.status_code == 202
        assert created.headers["cache-control"] == "no-store"
        document = created.json()["data"]
        assert document["status"] == "queued" and document["inspection_id"] is None
        assert (
            not {"url", "owner_hash", "url_ciphertext", "lease_owner", "fence"}
            & document.keys()
        )
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(MediaInspectionRow)
                )
                == 0
            )
            assert (
                await session.scalar(select(func.count()).select_from(OutboxEventRow))
                == 1
            )
        intent_id = UUID(document["id"])
        await executor.execute(InspectionCommand(str(intent_id), 0))
        observed = (await client.get(created.headers["location"])).json()["data"]
        assert observed["status"] == "ready" and observed["inspection_id"]
        repeated = await client.post(
            "/api/download-intents",
            json={"input": URL},
            headers={"Idempotency-Key": "same"},
        )
        assert repeated.status_code == 202 and repeated.json()["data"]["id"] == str(
            intent_id
        )
        await executor.execute(InspectionCommand(str(intent_id), 0))
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(MediaInspectionRow)
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count()).select_from(ResourceAdmissionRow)
                )
                == 1
            )
        conflict = await client.post(
            "/api/download-intents",
            json={"input": URL + "1"},
            headers={"Idempotency-Key": "same"},
        )
        assert conflict.status_code == 409
        app.dependency_overrides[get_current_user] = lambda: replace(
            TEST_USER, id=uuid4()
        )
        assert (await client.get(created.headers["location"])).status_code == 404
        assert (
            await client.post(created.headers["location"] + "/cancel")
        ).status_code == 404
        app.dependency_overrides[get_current_user] = lambda: TEST_USER
        assert (await client.post(created.headers["location"] + "/cancel")).json()[
            "data"
        ]["status"] == "cancelling"
    assert (await repo.get(intent_id, TEST_USER.owner_hash)).status == "cancelling"
    await repo.confirm_cancel(intent_id, 0, now=NOW)
    assert (await repo.get(intent_id, TEST_USER.owner_hash)).status == "cancelled"


async def test_intent_quota_replay_and_cancellation(postgres_engine):
    service, repo, _, _, sessions = components(postgres_engine)
    quota = UserQuota(max_active_per_owner=1)
    first = await service.create(URL, TEST_USER.owner_hash, "one", quota=quota)
    assert (
        await service.create(URL, TEST_USER.owner_hash, "one", quota=quota)
    ).id == first.id
    from app.services.quotas import QuotaExceeded

    with pytest.raises(QuotaExceeded, match="active_task_quota_exceeded"):
        await service.create(URL, TEST_USER.owner_hash, "two", quota=quota)
    await service.cancel(first.id, TEST_USER.owner_hash)
    await repo.confirm_cancel(first.id, 0, now=NOW)
    await service.create(URL, TEST_USER.owner_hash, "two", quota=quota)
    async with sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(ResourceAdmissionRow))
            == 2
        )


class WaitingRunner(FakeRunner):
    def __init__(self):
        super().__init__(runner_result())
        self.entered = asyncio.Event()
        self.stopped = asyncio.Event()

    async def inspect(self, url, **kwargs):
        self.entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.stopped.set()


async def test_user_cancel_stops_execution_and_cannot_publish_result(postgres_engine):
    runner = WaitingRunner()
    service, repo, executor, _, sessions = components(postgres_engine, runner)
    intent = await service.create(URL, TEST_USER.owner_hash, "cancel")
    work = asyncio.create_task(executor.execute(InspectionCommand(str(intent.id), 0)))
    await asyncio.wait_for(runner.entered.wait(), 2)
    await service.cancel(intent.id, TEST_USER.owner_hash)
    work.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(work, 2)
    assert runner.stopped.is_set()
    assert (await repo.get(intent.id, TEST_USER.owner_hash)).status == "cancelled"
    async with sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(MediaInspectionRow))
            == 0
        )


async def test_transient_failure_is_task_state_not_http_failure(postgres_engine):
    class Unavailable(FakeRunner):
        async def inspect(self, url, **kwargs):
            raise MediaInspectionFailure(
                failure=ProviderFailure.for_code("network_transient")
            )

    service, repo, executor, clock, _ = components(
        postgres_engine, Unavailable(runner_result())
    )
    intent = await service.create(URL, TEST_USER.owner_hash, "retry")
    await executor.execute(InspectionCommand(str(intent.id), 0))
    observed = await service.get(intent.id, TEST_USER.owner_hash)
    assert observed.reason_code == "transient"
    assert observed.status == "failed"


def test_openapi_intent_response_does_not_expose_execution_or_secrets():
    schema = create_app(Settings(app_env="test")).openapi()
    assert "202" in schema["paths"]["/api/download-intents"]["post"]["responses"]
    properties = schema["components"]["schemas"]["IntentResponse"]["properties"]
    assert (
        not {"url", "url_ciphertext", "owner_hash", "lease_owner", "fence"}
        & properties.keys()
    )


async def test_lost_acceptance_can_be_found_without_resubmitting_input(postgres_engine):
    service, _, _, clock, sessions = components(postgres_engine)
    intent = await service.create(URL, TEST_USER.owner_hash, "lost-response")
    clock[0] += timedelta(seconds=30)
    app = create_app(Settings(app_env="test"))
    app.state.services.intent_service = service
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        result = await client.get(
            "/api/download-intents", params={"idempotency_key": "lost-response"}
        )
        assert result.status_code == 200
        assert result.headers["cache-control"] == "no-store"
        recovered = result.json()["data"]
        assert recovered["id"] == str(intent.id)
        assert recovered["version"] == intent.version
        assert (
            datetime.fromisoformat(recovered["deadline"].replace("Z", "+00:00"))
            == intent.deadline
        )
        assert not {"input", "url", "owner_hash", "idempotency_key"} & recovered.keys()
        # The lookup must never create, reset or requeue work.
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(OutboxEventRow))
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count()).select_from(ResourceAdmissionRow)
                )
                == 1
            )
        app.dependency_overrides[get_current_user] = lambda: replace(
            TEST_USER, id=uuid4()
        )
        foreign = await client.get(
            "/api/download-intents", params={"idempotency_key": "lost-response"}
        )
        missing = await client.get(
            "/api/download-intents", params={"idempotency_key": "not-submitted"}
        )
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()
        for invalid in ("", "x" * 129):
            assert (
                await client.get(
                    "/api/download-intents", params={"idempotency_key": invalid}
                )
            ).status_code == 422


async def test_history_recovers_without_client_storage_and_is_bounded_and_owner_scoped(
    postgres_engine,
):
    service, _, executor, clock, sessions = components(postgres_engine)
    created = []
    for index in range(4):
        item = await service.create(URL, TEST_USER.owner_hash, f"history-{index}")
        created.append(item)
        if index == 0:
            await executor.execute(InspectionCommand(str(item.id), 0))
        else:
            await service.cancel(item.id, TEST_USER.owner_hash)
    other_owner = replace(TEST_USER, id=uuid4()).owner_hash
    foreign = await service.create(URL, other_owner, "foreign-history")
    app = create_app(Settings(app_env="test"))
    app.state.services.intent_service = service
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        first = await client.get("/api/download-intents/history", params={"limit": 2})
        assert first.status_code == 200
        assert first.headers["cache-control"] == "no-store"
        page = first.json()["data"]
        assert len(page["items"]) == 2
        # Concurrent insertion cannot shift an existing cursor page.
        clock[0] += timedelta(seconds=1)
        newest = await service.create(URL, TEST_USER.owner_hash, "history-new")
        second = await client.get(
            "/api/download-intents/history",
            params={"limit": 2, "before": page["next_cursor"]},
        )
        tail = second.json()["data"]
        assert tail["next_cursor"] is None
        items = page["items"] + tail["items"]
        assert [item["id"] for item in items] == sorted(
            [str(item.id) for item in created], reverse=True
        )
        assert str(newest.id) not in [item["id"] for item in items]
        resolved = next(item for item in items if item["id"] == str(created[0].id))
        assert resolved["status"] == "ready"
        assert resolved["title"]
        for item in items:
            assert (
                not {
                    "input",
                    "url",
                    "owner_hash",
                    "idempotency_key",
                    "url_ciphertext",
                    "lease_owner",
                }
                & item.keys()
            )
            restored = await client.get(f"/api/download-intents/{item['id']}")
            assert restored.json()["data"]["version"] == item["version"]
        for cursor in (foreign.id, uuid4()):
            assert (
                await client.get(
                    "/api/download-intents/history", params={"before": str(cursor)}
                )
            ).status_code == 404
        for limit in (0, 51):
            assert (
                await client.get(
                    "/api/download-intents/history", params={"limit": limit}
                )
            ).status_code == 422
    async with sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(OutboxEventRow)) == 9
        )
        assert (
            await session.scalar(select(func.count()).select_from(ResourceAdmissionRow))
            == 6
        )


async def test_expired_result_refresh_is_an_owned_202_on_the_same_intent(
    postgres_engine,
):
    service, repo, executor, clock, _ = components(postgres_engine)
    item = await service.create(URL, TEST_USER.owner_hash, "refresh-contract")
    await executor.execute(InspectionCommand(str(item.id), 0))
    clock[0] += timedelta(minutes=16)
    app = create_app(Settings(app_env="test"))
    app.state.services.intent_service = service
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        path = f"/api/download-intents/{item.id}/refresh"
        response = await client.post(path)
        assert response.status_code == 202
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["data"]["id"] == str(item.id)
        assert response.json()["data"]["status"] == "queued"
        assert (await client.post(path)).json() == response.json()
        app.dependency_overrides[get_current_user] = lambda: replace(
            TEST_USER, id=uuid4()
        )
        assert (await client.post(path)).status_code == 404
        app.dependency_overrides[get_current_user] = lambda: TEST_USER
        await service.cancel(item.id, TEST_USER.owner_hash)
        assert (await client.post(path)).status_code == 409
        cancelled = await repo.get(item.id, TEST_USER.owner_hash)
        await repo.confirm_cancel(item.id, cancelled.generation, now=clock[0])
        assert (await client.post(path)).status_code == 409


async def test_failed_intent_persists_and_projects_safe_attempt_evidence(
    postgres_engine,
):
    from app.services.provider_failures import FailureEvidenceKind

    facts = {
        "kind": "upstream_response",
        "layer": "L2",
        "client": "youtube:tv",
        "egress_route": "global_residential",
        "egress_revision": "safe-revision",
        "egress_class": "datacenter",
        "egress_observed_ip": "192.0.2.1",
        "identity_used": True,
    }

    class Failed(FakeRunner):
        async def inspect(self, url, **kwargs):
            raise MediaInspectionFailure(
                failure=ProviderFailure.for_code(
                    "network_blocked",
                    layer="L2",
                    evidence_kind=FailureEvidenceKind.UPSTREAM_RESPONSE,
                    evidence=facts,
                )
            )

    service, repo, executor, clock, _ = components(
        postgres_engine, Failed(runner_result())
    )
    intent = await service.create(URL, TEST_USER.owner_hash, "failed-evidence")
    await executor.execute(InspectionCommand(str(intent.id), 0))
    persisted = await repo.get(intent.id, TEST_USER.owner_hash)
    assert persisted.latest_failure.evidence == facts
    app = create_app(Settings(app_env="test"))
    app.state.services.intent_service = service
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(f"/api/download-intents/{intent.id}")
    assert response.status_code == 200
    assert response.json()["data"]["failure"]["evidence"] == facts
    assert "execution_context" not in response.json()["data"]
