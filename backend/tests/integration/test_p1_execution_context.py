"""Stub layers through Runner, preparation and real PostgreSQL persistence."""

from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.integrations.media_runner import _inspection_result
from app.models import ArtifactRow, DownloadJobRow, MediaInspectionRow
from app.models.download_intent import DownloadIntentRow
from app.repositories.contracts import ArtifactCreate
from app.repositories.downloads.intent_repository import IntentRepository
from app.repositories.downloads.repository import SqlAlchemyDownloadRepository
from app.schemas.downloads import DownloadResponse
from app.schemas.inspections import InspectionResponse
from app.services.downloads.download_models import DownloadCreate
from app.services.downloads.fingerprints import HmacRequestFingerprinter
from app.services.downloads.inspect_media import InspectMedia
from app.services.downloads.views import download_view, inspection_view
from app.services.provider_types import Layer
from app.workers.runner.engine.ladder import LAYER_TABLE
from app.workers.runner.engine.resolved import ResolvedMedia
from app.workers.runner.service import MediaRunnerService
from app.workers.runner.utilities import normalize_for_settings
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.integration.test_download_intents import OWNER, command
from tests.unit.services.fakes import FakeCipher, FakeValidator
from tests.unit.workers.runner.helpers import settings, split_media_info


class Browser:
    def __init__(self):
        self.events = []

    async def close(self):
        self.events.append(("close", None))


def resolved(ctx):
    media = normalize_for_settings(
        split_media_info(), settings(Path("/tmp/p1-fixture"))
    )
    return ResolvedMedia(
        **{field.name: getattr(media, field.name) for field in fields(media)},
        client="stub:actual",
        run_context=ctx,
    )


@pytest.mark.parametrize(
    "layer,url",
    [
        (Layer.L2, "https://www.youtube.com/watch?v=stub"),
        (Layer.L3, "https://www.tiktok.com/@stub/video/123"),
    ],
)
async def test_actual_layer_context_persists_and_is_public(
    postgres_engine, tmp_path, monkeypatch, layer, url
):
    now = datetime.now(UTC)
    service = MediaRunnerService(settings(tmp_path))
    browser = Browser()

    class Success:
        async def resolve(self, source, ctx):
            return resolved(
                ctx.with_material(browser=browser) if layer is Layer.L3 else ctx
            )

    class Fail:
        async def resolve(self, source, ctx):
            from app.workers.runner.errors import RunnerFailure

            raise RunnerFailure("challenge")

    monkeypatch.setitem(LAYER_TABLE, Layer.L1, Fail)
    monkeypatch.setitem(LAYER_TABLE, layer, Success)

    class Runner:
        async def inspect(self, url, **kwargs):
            return _inspection_result(await service.inspect(url, **kwargs))

    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    intents = IntentRepository(sessions)
    downloads = SqlAlchemyDownloadRepository(sessions)
    accepted = await intents.accept(command(), now=now)
    operation = await intents.claim(accepted.id, accepted.generation, now=now)
    prepare = InspectMedia(
        repository=downloads,
        runner=Runner(),
        url_validator=FakeValidator(),
        url_cipher=FakeCipher(),
        fingerprinter=HmacRequestFingerprinter(b"k" * 32),
        now=lambda: now,
        new_id=uuid4,
        inspection_ttl=timedelta(hours=1),
        max_duration_seconds=3600,
    )
    result = await prepare.prepare(
        url,
        OWNER,
        f"intent:{accepted.id}:{accepted.generation}",
        deadline=accepted.deadline,
    )
    saved = await intents.complete(operation.intent, result, now=now)
    context = saved.execution_context
    assert context.resolved_layer == layer and context.client == "stub:actual"
    assert context.browser_context_kind == (
        "anonymous" if layer is Layer.L3 else "none"
    )
    document = context.to_document()
    if layer is Layer.L3:
        assert browser.events == [("close", None)]
    selected = result.formats[0]
    job = (
        await downloads.create_job(
            DownloadCreate(
                uuid4(),
                result.id,
                selected.id,
                OWNER,
                "confirm",
                "e" * 64,
                selected.semantic_plan,
            ),
            now=now,
        )
    ).job
    lease = await downloads.claim_job(job.id, "worker", now, timedelta(minutes=1))
    await downloads.record_execution_context(
        job.id, "worker", lease.attempt, context, now
    )
    await downloads.heartbeat(
        job.id,
        "worker",
        lease.attempt,
        stage="uploading",
        stage_rank=5,
        progress=95,
        now=now,
        lease_for=timedelta(minutes=1),
    )
    artifact = await downloads.complete_success(
        job.id,
        "worker",
        lease.attempt,
        ArtifactCreate(
            bucket="test",
            sha256="a" * 64,
            size_bytes=1024,
            duration_ms=30000,
            container="mp4",
            content_type="video/mp4",
            media_metadata={"execution_context": document},
        ),
        now=now,
    )
    async with sessions() as session:
        assert (
            await session.get(DownloadIntentRow, accepted.id)
        ).execution_context == document
        assert (await session.get(MediaInspectionRow, result.id)).metadata_json[
            "execution_context"
        ] == document
        assert (await session.get(DownloadJobRow, job.id)).execution_context == document
        assert (await session.get(ArtifactRow, artifact.id)).media_metadata[
            "execution_context"
        ] == document
    inspection = await downloads.get_inspection(result.id, OWNER, now)
    current_job = await downloads.get_job(job.id)
    public_inspection = InspectionResponse.from_view(
        inspection_view(inspection)
    ).model_dump(mode="json")
    public_job = DownloadResponse.from_view(download_view(current_job)).model_dump(
        mode="json"
    )
    assert (
        public_inspection["execution_context"]
        == public_job["execution_context"]
        == document
    )
    assert len(document) == 12
