"""Real PostgreSQL guards and current-state normalization for R0 contexts."""

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.models import ArtifactRow, DownloadJobRow, MediaInspectionRow
from app.models.download_intent import DownloadIntentRow
from app.repositories.contracts import ArtifactCreate
from app.services.provider_failures import FailurePhase, ProviderFailure
from pydantic import TypeAdapter
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from tests.integration.test_download_intents import NOW, OWNER
from tests.integration.test_intent_handoff import ready
from tests.postgres import isolated_postgres_engine


async def apply_schema(engine, sql):
    async with engine.connect() as connection:
        schema = await connection.scalar(text("SELECT current_schema()"))
        assert schema.startswith("test_") and schema.replace("_", "").isalnum()
        await connection.execute(text(f'SET search_path TO "{schema}", public'))
        await connection.commit()
        raw = await connection.get_raw_connection()
        await raw.driver_connection.execute(sql)


async def test_schema_restores_generation_for_existing_intents():
    sql = (Path(__file__).resolve().parents[2] / "sql/schema.sql").read_text(
        encoding="utf-8"
    )
    async with isolated_postgres_engine() as engine:
        await apply_schema(engine, sql)
        _, _, _, intent, _ = await ready(engine)
        async with engine.begin() as connection:
            before = (
                await connection.execute(
                    text(
                        "SELECT id, status, version, inspection_id "
                        "FROM download_intents"
                    )
                )
            ).one()
            await connection.execute(
                text("ALTER TABLE download_intents DROP COLUMN generation")
            )

        await apply_schema(engine, sql)
        await apply_schema(engine, sql)

        async with engine.begin() as connection:
            after = (
                await connection.execute(
                    text(
                        "SELECT id, status, version, inspection_id "
                        "FROM download_intents"
                    )
                )
            ).one()
            assert after == before
            assert (
                await connection.scalar(
                    text("SELECT generation FROM download_intents WHERE id = :id"),
                    {"id": intent.id},
                )
                == 0
            )
            await connection.execute(
                text("UPDATE download_intents SET generation = 2 WHERE id = :id"),
                {"id": intent.id},
            )

        await apply_schema(engine, sql)
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT generation FROM download_intents WHERE id = :id"),
                    {"id": intent.id},
                )
                == 2
            )
            with pytest.raises(IntegrityError, match="generation"):
                await connection.execute(
                    text("UPDATE download_intents SET generation = -1 WHERE id = :id"),
                    {"id": intent.id},
                )


async def saved_chain(engine):
    sessions, intents, downloads, intent, create = await ready(engine)
    job = (await downloads.create_job(create, now=NOW)).job
    context = intent.execution_context
    claimed = await downloads.claim_job(job.id, "worker", NOW, timedelta(minutes=1))
    await downloads.record_execution_context(
        job.id, "worker", claimed.attempt, context, NOW
    )
    await downloads.heartbeat(
        job.id,
        "worker",
        claimed.attempt,
        stage="uploading",
        stage_rank=5,
        progress=95,
        now=NOW,
        lease_for=timedelta(minutes=1),
    )
    artifact = await downloads.complete_success(
        job.id,
        "worker",
        claimed.attempt,
        ArtifactCreate(
            bucket="test",
            sha256="a" * 64,
            size_bytes=1024,
            duration_ms=10_000,
            container="mp4",
            content_type="video/mp4",
            media_metadata={
                "execution_context": context.to_document(),
                "video_streams": 1,
            },
        ),
        now=NOW,
    )
    return sessions, intent, job, artifact, context.to_document()


async def test_context_persists_unchanged_from_intent_through_artifact(postgres_engine):
    sessions, intent, job, artifact, document = await saved_chain(postgres_engine)
    async with sessions() as session:
        stored_intent = await session.get(DownloadIntentRow, intent.id)
        stored_inspection = await session.get(MediaInspectionRow, intent.inspection_id)
        stored_job = await session.get(DownloadJobRow, job.id)
        stored_artifact = await session.get(ArtifactRow, artifact.id)
        assert stored_intent.execution_context == document
        assert stored_inspection.metadata_json["execution_context"] == document
        assert stored_job.execution_context == document
        assert stored_artifact.media_metadata["execution_context"] == document
        assert len(document) == 12


async def test_all_four_persistence_guards_reject_incomplete_or_sensitive_context(
    postgres_engine,
):
    sessions, intent, job, artifact, document = await saved_chain(postgres_engine)
    targets = [
        (DownloadIntentRow, intent.id, "execution_context"),
        (DownloadJobRow, job.id, "execution_context"),
        (MediaInspectionRow, intent.inspection_id, "metadata_json"),
        (ArtifactRow, artifact.id, "media_metadata"),
    ]
    invalid = [
        None,
        {k: v for k, v in document.items() if k != "registry_revision"},
        {**document, "cookies": "untrusted-material"},
        {**document, "engine_revision": "bad value"},
        {**document, "identity_used": "false"},
        {**document, "identity_digest": "unrequested-identity"},
        {**document, "identity_used": True},
        {**document, "egress_observed_ip": "not-an-ip"},
        {**document, "egress_observed_ip": "127.1"},
        {**document, "egress_observed_ip": "127.00.0.1"},
        {**document, "egress_observed_ip": "127.0.0.1/32"},
        {**document, "egress_class": "untrusted"},
        {**document, "resolved_layer": "L4"},
        {**document, "browser_context_kind": "authenticated"},
    ]
    for model, identity, column in targets:
        for value in invalid:
            if value is None and column == "execution_context":
                continue  # SQL NULL represents an operation that has not executed.
            changed = (
                value if column == "execution_context" else {"execution_context": value}
            )
            async with sessions() as session:
                with pytest.raises(IntegrityError, match="execution_context"):
                    await session.execute(
                        update(model)
                        .where(model.id == identity)
                        .values(**{column: changed})
                    )
                await session.rollback()


async def test_schema_projects_old_error_meaning_and_preserves_business_rows():
    sql = (Path(__file__).resolve().parents[2] / "sql/schema.sql").read_text(
        encoding="utf-8"
    )
    mapping = {
        "inspection_timeout": "transient",
        "provider_access_policy_not_allowed": "invalid_input",
        "provider_auth_required": "login_required",
        "provider_content_restricted": "content_unavailable",
        "provider_drm_protected": "content_protected",
        "provider_geo_restricted": "network_blocked",
        "provider_guest_context_required": "challenge",
        "provider_link_unavailable": "content_unavailable",
        "provider_media_unsupported": "invalid_input",
        "provider_rate_limited": "rate_limited",
        "provider_session_expired": "identity_unavailable",
        "provider_session_not_ready": "identity_unavailable",
        "provider_temporarily_unavailable": "transient",
        "provider_unsupported": "invalid_input",
        "provider_verification_failed": "challenge",
        "unknown_future_code": "internal_error",
    }
    async with isolated_postgres_engine() as engine:
        await apply_schema(engine, sql)
        sessions, intent, job, artifact, document = await saved_chain(engine)
        failure = ProviderFailure.for_code(
            "rate_limited",
            phase=FailurePhase.PUBLISH,
            gate="none",
            evidence={
                "kind": "unknown",
                "cause_code": None,
                "http_status": 429,
                "returncode": None,
            },
            retry_after=NOW + timedelta(seconds=30),
        )
        failure_document = TypeAdapter(ProviderFailure).dump_python(
            failure, mode="json"
        )
        identities = {}
        async with sessions() as session, session.begin():
            for old in mapping:
                identity = uuid4()
                identities[old] = identity
                session.add(
                    DownloadJobRow(
                        id=identity,
                        source_kind="browser_import",
                        owner_hash=OWNER,
                        idempotency_key=old,
                        request_fingerprint="b" * 64,
                        semantic_plan={},
                        status="failed",
                        error_code=old,
                    )
                )
            stale = await session.get(DownloadIntentRow, intent.id)
            stale.reason_code = "provider_auth_required"
            stale.latest_failure = failure_document
        tables = (DownloadIntentRow, DownloadJobRow, MediaInspectionRow, ArtifactRow)
        async with sessions() as session:
            before = {
                model.__tablename__: await session.scalar(
                    select(func.count()).select_from(model)
                )
                for model in tables
            }
        for _ in range(2):
            await apply_schema(engine, sql)
            async with sessions() as session:
                for old, expected in mapping.items():
                    assert (
                        await session.get(DownloadJobRow, identities[old])
                    ).error_code == expected
                assert (
                    await session.get(DownloadIntentRow, intent.id)
                ).reason_code == "login_required"
                assert (await session.get(ArtifactRow, artifact.id)).media_metadata == {
                    "execution_context": document,
                    "video_streams": 1,
                }
                assert (
                    await session.get(DownloadIntentRow, intent.id)
                ).execution_context == document
                assert (
                    await session.get(DownloadIntentRow, intent.id)
                ).latest_failure == failure_document
                after = {
                    model.__tablename__: await session.scalar(
                        select(func.count()).select_from(model)
                    )
                    for model in tables
                }
                assert after == before


async def test_schema_invalidates_old_context_and_preserves_business_records():
    sql = (Path(__file__).resolve().parents[2] / "sql/schema.sql").read_text(
        encoding="utf-8"
    )
    async with isolated_postgres_engine() as engine:
        await apply_schema(engine, sql)
        sessions, intent, job, artifact, document = await saved_chain(engine)
        legacy = {
            "provider_key": "generic",
            "resolved_layer": "L1",
            "egress_route": "default",
            "client_profile": "yt-dlp-default",
            "identity_used": False,
            "engine_version": "old",
        }
        async with engine.begin() as connection:
            for table in (
                "download_intents",
                "download_jobs",
                "media_inspections",
                "artifacts",
            ):
                await connection.execute(
                    text(
                        f"ALTER TABLE {table} DROP CONSTRAINT "
                        f"ck_{table}_execution_context"
                    )
                )
        async with sessions() as session, session.begin():
            (await session.get(DownloadIntentRow, intent.id)).execution_context = legacy
            (await session.get(DownloadJobRow, job.id)).execution_context = legacy
            (
                await session.get(MediaInspectionRow, intent.inspection_id)
            ).metadata_json = {"execution_context": legacy, "title_hint": "preserved"}
            (await session.get(ArtifactRow, artifact.id)).media_metadata = {
                "execution_context": legacy,
                "video_streams": 1,
            }
        for _ in range(2):
            await apply_schema(engine, sql)
            async with sessions() as session:
                assert (
                    await session.get(DownloadIntentRow, intent.id)
                ).execution_context is None
                assert (
                    await session.get(DownloadJobRow, job.id)
                ).execution_context is None
                assert (
                    await session.get(MediaInspectionRow, intent.inspection_id)
                ).metadata_json == {"title_hint": "preserved"}
                assert (await session.get(ArtifactRow, artifact.id)).media_metadata == {
                    "video_streams": 1
                }
                assert (
                    await session.scalar(
                        select(func.count()).select_from(DownloadIntentRow)
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(DownloadJobRow)
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(MediaInspectionRow)
                    )
                    == 1
                )
                assert (
                    await session.scalar(select(func.count()).select_from(ArtifactRow))
                    == 1
                )
