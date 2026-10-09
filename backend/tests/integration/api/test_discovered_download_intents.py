"""Selected article videos use ordinary durable admission and its quotas."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from app.api.deps import get_current_user
from app.core.config import Settings
from app.core.security.url_cipher import URLCipher
from app.integrations.article_discovery.parser import parse_article_html
from app.integrations.url_security import FernetUrlEnvelope, MediaUrlValidator
from app.main import create_app
from app.models import OutboxEventRow
from app.repositories.downloads.intent_repository import IntentRepository
from app.repositories.source_discoveries.repository import (
    SqlAlchemySourceDiscoveryRepository,
)
from app.services.downloads.errors import ApplicationError, ApplicationErrorCode
from app.services.downloads.fingerprints import HmacRequestFingerprinter
from app.services.downloads.intents import IntentService
from app.services.quotas import QuotaExceeded, UserQuota
from app.services.source_discoveries.use_cases import CreateSourceDiscovery
from cryptography.fernet import Fernet
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.integration.api.test_download_intent_routes import NOW
from tests.integration.api.test_download_routes import TEST_USER
from tests.unit.integrations.test_article_native_video import article

ARTICLE = "https://mp.weixin.qq.com/s/article_123"


class Adapter:
    def __init__(self, page=None):
        self.page = article() if page is None else page
        self.calls = 0

    async def discover(self, url):
        assert url == ARTICLE
        self.calls += 1
        return parse_article_html(self.page)


async def setup(engine, *, page=None):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    cipher = FernetUrlEnvelope(URLCipher(Fernet.generate_key()), key_id="test")
    fingerprint = HmacRequestFingerprinter(b"f" * 32)
    clock = [NOW]
    discoveries = SqlAlchemySourceDiscoveryRepository(sessions)
    adapter = Adapter(page)
    discover = CreateSourceDiscovery(
        discoveries,
        adapter,
        cipher,
        fingerprint,
        now=lambda: clock[0],
        new_id=uuid4,
        ttl=timedelta(minutes=10),
        max_items=24,
    )
    selected = await discover(ARTICLE, TEST_USER.owner_hash, "discover")
    repository = IntentRepository(sessions)
    service = IntentService(
        repository,
        MediaUrlValidator(),
        cipher,
        fingerprint,
        now=lambda: clock[0],
        new_id=uuid4,
        discoveries=discoveries,
        article_adapter=adapter,
    )
    return service, selected, sessions, clock, adapter


async def test_native_selection_is_owner_scoped_durable_and_replay_uses_same_quota(
    postgres_engine,
):
    service, discovery, sessions, clock, adapter = await setup(postgres_engine)
    item = discovery.items[0]
    app = create_app(Settings(app_env="test"))
    app.state.services.intent_service = service
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    source = {
        "kind": "discovered_item",
        "discovery_id": str(discovery.id),
        "item_ref": str(item.item_ref),
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        app.dependency_overrides[get_current_user] = lambda: replace(
            TEST_USER, id=uuid4()
        )
        assert (
            await client.post(
                "/api/download-intents",
                json={"source": source},
                headers={"Idempotency-Key": "owned"},
            )
        ).status_code == 404
        app.dependency_overrides[get_current_user] = lambda: TEST_USER
        for body in (
            {},
            {"input": ARTICLE, "source": source},
            {"source": {**source, "kind": "public_url"}},
        ):
            assert (
                await client.post(
                    "/api/download-intents",
                    json=body,
                    headers={"Idempotency-Key": "bad"},
                )
            ).status_code == 422
        first = await client.post(
            "/api/download-intents",
            json={"source": source},
            headers={"Idempotency-Key": "owned"},
        )
        assert first.status_code == 202 and first.json()["data"]["status"] == "queued"
        assert "qpic" not in first.text and "video=" not in first.text
        repeated = await client.post(
            "/api/download-intents",
            json={"source": source},
            headers={"Idempotency-Key": "owned"},
        )
        assert repeated.json()["data"]["id"] == first.json()["data"]["id"]
    assert (
        adapter.calls == 1
    )  # Native re-resolution belongs to Runner, after admission.
    async with sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(OutboxEventRow)) == 1
        )
    with pytest.raises(QuotaExceeded):
        await service.create_discovered(
            discovery.id,
            item.item_ref,
            TEST_USER.owner_hash,
            "new",
            quota=UserQuota(max_active_per_owner=1),
        )
    clock[0] = NOW + timedelta(minutes=11)
    with pytest.raises(ApplicationError) as caught:
        await service.create_discovered(
            discovery.id, item.item_ref, TEST_USER.owner_hash, "expired"
        )
    assert caught.value.code == ApplicationErrorCode.NOT_FOUND


async def test_external_selection_revalidates_exact_identity_and_stops_if_changed(
    postgres_engine,
):
    page = '<div id="js_content"><iframe src="https://v.qq.com/x/page/tencent123.html"></iframe></div>'
    service, discovery, sessions, _, adapter = await setup(postgres_engine, page=page)
    adapter.page = page.replace("tencent123", "different123")
    with pytest.raises(ApplicationError) as caught:
        await service.create_discovered(
            discovery.id, discovery.items[0].item_ref, TEST_USER.owner_hash, "changed"
        )
    assert caught.value.code == ApplicationErrorCode.CONTENT_UNAVAILABLE
    async with sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(OutboxEventRow)) == 0
        )
    adapter.page = page
    intent = await service.create_discovered(
        discovery.id, discovery.items[0].item_ref, TEST_USER.owner_hash, "valid"
    )
    assert intent.status == "queued"
