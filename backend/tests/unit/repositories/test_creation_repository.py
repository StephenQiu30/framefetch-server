"""Real PostgreSQL behavior for ownership, immutable work and unsafe retries."""

import base64
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from app.core.db import utc_now
from app.core.errors import AppError
from app.integrations.messaging.envelope import EventEnvelope
from app.models.analysis_worker import AnalysisWorkerHeartbeatRow
from app.models.creation import CreationRevisionRow
from app.models.outbox import OutboxEventRow
from app.repositories.creation import CreationRepository
from app.services.creation.exports import ExportArtifact
from app.services.creation.models import (
    CreationBudget,
    CreationConfirmRequest,
    CreationMaterialCreateRequest,
    CreationRevisionSaveRequest,
    CreationTaskCreateRequest,
)
from app.services.creation.service import CreationService
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.integration.test_execution_context_schema import apply_schema
from tests.postgres import isolated_postgres_engine

OWNER = "a" * 64
OTHER = "b" * 64


@pytest.fixture
def repository(postgres_engine):
    return CreationRepository(
        async_sessionmaker(postgres_engine, expire_on_commit=False)
    )


async def material(repository, *, text="这是保留的原文。"):
    value = await repository.create_material(
        OWNER,
        str(uuid4()),
        CreationMaterialCreateRequest(
            kind="text",
            title="原创材料",
            text=text,
            rights_statement="本人原创，允许本次处理",
        ),
    )
    return await repository.confirm_material(
        value.id,
        OWNER,
        CreationConfirmRequest(expected_revision_id=value.current_revision.id),
    )


async def task(repository, source=None, *, key=None, max_calls=4):
    source = source or await material(repository)
    request = CreationTaskCreateRequest(
        skill_id="article-edit",
        material_revision_ids=(source.current_revision.id,),
        budget=CreationBudget(max_calls=max_calls),
    )
    return await repository.create_task(OWNER, key or str(uuid4()), request, "c" * 64)


async def test_confirmed_result_source_is_fixed_and_invalidates_descendants(repository):
    parent = await task(repository)
    await repository.claim_task(parent.id, "parent-worker", expected_attempt=1)
    parent = await repository.finish_task(
        parent.id, "parent-worker", "固定母稿", {"claims": []}
    )
    source_id = parent.revision.id
    request = CreationMaterialCreateRequest(
        kind="text",
        title="公众号母稿",
        source_revision_id=source_id,
        rights_statement="本人原创",
    )
    with pytest.raises(AppError) as unconfirmed:
        await repository.create_material(OWNER, "derived", request)
    assert unconfirmed.value.status == 409
    await repository.confirm_task(
        parent.id, OWNER, CreationConfirmRequest(expected_revision_id=source_id)
    )
    with pytest.raises(AppError) as false_source:
        await repository.create_material(
            OWNER, "false-source", request.model_copy(update={"text": "不同稿"})
        )
    assert false_source.value.status == 422
    with pytest.raises(AppError) as foreign:
        await repository.create_material(OTHER, "foreign", request)
    assert foreign.value.status == 404
    derived = await repository.create_material(OWNER, "derived", request)
    assert derived.source_revision_id == source_id
    assert derived.current_revision.text == "固定母稿"
    assert derived.current_revision.parent_revision_id == source_id
    await repository.confirm_material(
        derived.id,
        OWNER,
        CreationConfirmRequest(expected_revision_id=derived.current_revision.id),
    )
    child = await task(repository, derived)
    await repository.claim_task(child.id, "child-worker", expected_attempt=1)
    child = await repository.finish_task(child.id, "child-worker", "公众号候选", {})
    await repository.confirm_task(
        child.id, OWNER, CreationConfirmRequest(expected_revision_id=child.revision.id)
    )
    grand_material = await repository.create_material(
        OWNER,
        "grand-material",
        request.model_copy(update={"source_revision_id": child.revision.id}),
    )
    await repository.confirm_material(
        grand_material.id,
        OWNER,
        CreationConfirmRequest(expected_revision_id=grand_material.current_revision.id),
    )
    grandchild = await task(repository, grand_material)
    await repository.save_task_revision(
        parent.id,
        OWNER,
        "parent-edit",
        CreationRevisionSaveRequest(
            expected_revision_id=source_id, text="母稿第二版", data={}
        ),
    )
    assert (await repository.get_task(child.id, OWNER)).stale
    assert (await repository.get_task(grandchild.id, OWNER)).stale
    fixed = await repository.get_material(derived.id, OWNER)
    assert fixed.current_revision.id == derived.current_revision.id
    assert fixed.current_revision.sha256 == derived.current_revision.sha256
    assert fixed.current_revision.text == "固定母稿"
    stale_source_task = await task(repository, derived)
    assert stale_source_task.stale


async def test_url_only_reference_and_oversized_candidate_never_publish(repository):
    service = CreationService(repository)
    reference = await service.create_material(
        OWNER,
        "url-reference",
        CreationMaterialCreateRequest(
            kind="reference",
            title="待核查网页",
            source_url="https://example.com/article",
            rights_statement="有权参考",
        ),
    )
    await repository.confirm_material(
        reference.id,
        OWNER,
        CreationConfirmRequest(expected_revision_id=reference.current_revision.id),
    )
    for skill in ("article-write", "film-research", "source-extract"):
        with pytest.raises(AppError) as missing:
            await service.create_task(
                OWNER,
                f"url-{skill}",
                CreationTaskCreateRequest(
                    skill_id=skill,
                    material_revision_ids=(reference.current_revision.id,),
                ),
            )
        assert missing.value.status == 422
    value = await task(repository)
    await repository.claim_task(value.id, "bounded-worker", expected_attempt=1)
    with pytest.raises(ValueError):
        await repository.finish_task(
            value.id, "bounded-worker", "正文", {"overbound": "x" * (1024 * 1024)}
        )
    stored = await repository.get_task(value.id, OWNER)
    assert stored.status.value == "processing" and stored.revision is None
    failed = await repository.fail_task(
        value.id, "bounded-worker", "creation_execution_failed"
    )
    assert failed.status.value == "failed" and failed.revision is None


async def test_legacy_worker_heartbeat_cannot_admit_creation(repository):
    async with repository._sessions() as session, session.begin():
        session.add(
            AnalysisWorkerHeartbeatRow(
                worker_id="legacy-worker",
                app_version="test",
                message_schema_version=2,
                last_seen_at=utc_now(),
            )
        )
    assert not (await repository.runtime_availability())[1]
    async with repository._sessions() as session, session.begin():
        session.add(
            AnalysisWorkerHeartbeatRow(
                worker_id="creation-worker",
                app_version="test",
                message_schema_version=3,
                last_seen_at=utc_now(),
            )
        )
    assert (await repository.runtime_availability())[1]


async def test_owned_confirmed_material_and_task_outbox_are_atomic(repository):
    unconfirmed = await repository.create_material(
        OWNER,
        "source",
        CreationMaterialCreateRequest(
            kind="text", title="原文", text="有权原稿", rights_statement="原创"
        ),
    )
    request = CreationTaskCreateRequest(
        skill_id="article-edit",
        material_revision_ids=(unconfirmed.current_revision.id,),
    )
    with pytest.raises(AppError) as rejected:
        await repository.create_task(OWNER, "task", request, "c" * 64)
    assert rejected.value.status == 409
    await repository.confirm_material(
        unconfirmed.id,
        OWNER,
        CreationConfirmRequest(expected_revision_id=unconfirmed.current_revision.id),
    )
    first = await repository.create_task(OWNER, "task", request, "c" * 64)
    replay = await repository.create_task(OWNER, "task", request, "c" * 64)
    assert first.id == replay.id
    with pytest.raises(AppError) as mismatch:
        await repository.create_task(
            OWNER,
            "task",
            request.model_copy(update={"options": {"mode": "polish"}}),
            "c" * 64,
        )
    assert mismatch.value.status == 409
    with pytest.raises(AppError) as invisible:
        await repository.get_task(first.id, OTHER)
    assert invisible.value.status == 404
    async with repository._sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(OutboxEventRow)) == 1
        )
        event = await session.scalar(select(OutboxEventRow))
        envelope = EventEnvelope(
            1,
            event.id,
            event.aggregate_id,
            event.event_type,
            event.created_at,
            event.payload,
        )
        assert envelope.payload == {
            "task_id": str(first.id),
            "attempt": 1,
            "request_id": event.payload["request_id"],
        }
        assert "有权原稿" not in envelope.to_bytes().decode()


async def test_manual_material_versions_remain_readable_and_mark_pinned_tasks_stale(
    repository,
):
    source = await material(repository)
    existing = await task(repository, source)
    save = CreationRevisionSaveRequest(
        expected_revision_id=source.current_revision.id,
        text="作者改过的新原文。",
        data={"note": "人工"},
    )
    new = await repository.save_material_revision(source.id, OWNER, "manual-save", save)
    replay = await repository.save_material_revision(
        source.id, OWNER, "manual-save", save
    )
    assert new.current_revision.id == replay.current_revision.id
    assert new.current_revision.number == 2
    with pytest.raises(AppError) as conflict:
        await repository.save_material_revision(
            source.id, OWNER, "different-save", save
        )
    assert conflict.value.status == 409
    revisions = await repository.list_material_revisions(source.id, OWNER)
    assert [item.text for item in revisions] == [
        "作者改过的新原文。",
        "这是保留的原文。",
    ]
    frozen = await repository.task_materials(existing.id, OWNER)
    assert frozen[0]["text"] == source.current_revision.text
    assert frozen[0]["sha256"] == source.current_revision.sha256
    assert (await repository.get_task(existing.id, OWNER)).stale


async def test_unknown_call_cancel_and_worker_recovery_never_free_reservation(
    repository,
):
    created = await task(repository, max_calls=1)
    worker = f"creation/{created.id}/1"
    claimed = await repository.claim_task(created.id, worker, expected_attempt=1)
    assert claimed is not None
    await repository.mark_call_sent(created.id, worker)
    await repository.cancel_task(created.id, OWNER)
    await repository.settle_call(created.id, worker, known=False)
    await repository.fail_task(
        created.id, worker, "analysis_outcome_unknown", outcome_unknown=True
    )
    cancelled = await repository.get_task(created.id, OWNER)
    assert cancelled.status == "cancelled"
    assert cancelled.usage.calls_reserved == 1
    assert cancelled.usage.unknown_operations == 1
    assert cancelled.usage.tokens_reserved == created.budget.max_tokens
    with pytest.raises(AppError) as blocked:
        await repository.retry_task(created.id, OWNER, "retry-unknown")
    assert blocked.value.status == 409
    assert await repository.claim_task(created.id, worker, expected_attempt=1) is None
    after = await repository.finish_task(created.id, worker, "迟到候选", {})
    assert after.revision is None


async def test_not_sent_is_released_but_known_execution_consumes_task_budget(
    repository,
):
    created = await task(repository, max_calls=1)
    worker = f"creation/{created.id}/1"
    await repository.claim_task(created.id, worker, expected_attempt=1)
    await repository.mark_call_sent(created.id, worker)
    await repository.settle_call(created.id, worker, known=True, executed=False)
    released = await repository.get_task(created.id, OWNER)
    assert released.usage.calls_used == released.usage.calls_reserved == 0
    await repository.mark_call_sent(created.id, worker)
    await repository.settle_call(created.id, worker, known=True)
    await repository.fail_task(created.id, worker, "invalid_model_output")
    with pytest.raises(AppError) as exhausted:
        await repository.retry_task(created.id, OWNER, "exhausted")
    assert exhausted.value.code == "analysis_budget_exceeded"


async def test_attempt_fence_rejects_old_workflow_and_preserves_confirmed_export(
    repository,
):
    created = await task(repository)
    await repository.cancel_task(created.id, OWNER)
    second = await repository.retry_task(created.id, OWNER, "new-attempt")
    assert second.attempt == 2
    assert (
        await repository.claim_task(created.id, "old-worker", expected_attempt=1)
        is None
    )
    worker = f"creation/{created.id}/2"
    await repository.claim_task(created.id, worker, expected_attempt=2)
    ready = await repository.finish_task(
        created.id, worker, "人工需要确认的正文", {"summary": "候选"}
    )
    assert ready.revision and not ready.revision.confirmed
    artifact = ExportArtifact("article.md", "text/markdown", "确认后的交付".encode())
    with pytest.raises(AppError):
        await repository.save_export(
            created.id, ready.revision.id, "md", OWNER, artifact
        )
    await repository.confirm_task(
        created.id,
        OWNER,
        CreationConfirmRequest(expected_revision_id=ready.revision.id),
    )
    saved = await repository.save_export(
        created.id, ready.revision.id, "md", OWNER, artifact
    )
    replay = await repository.save_export(
        created.id,
        ready.revision.id,
        "md",
        OWNER,
        ExportArtifact("different.md", "text/markdown", b"must not replace"),
    )
    assert saved.data == replay.data == artifact.data
    edited = await repository.save_task_revision(
        created.id,
        OWNER,
        "edit-result",
        CreationRevisionSaveRequest(
            expected_revision_id=ready.revision.id, text="新人工正文", data={}
        ),
    )
    assert edited.revision.number == 2 and not edited.revision.confirmed
    assert (
        await repository.get_export(created.id, ready.revision.id, "md", OWNER)
    ).data == artifact.data
    with pytest.raises(AppError) as invisible:
        await repository.get_export(created.id, ready.revision.id, "md", OTHER)
    assert invisible.value.status == 404


async def test_actual_image_original_is_validated_and_protected_across_metadata_edits(
    repository,
):
    image = BytesIO()
    Image.new("RGB", (12, 12), "white").save(image, format="PNG")
    original = image.getvalue()
    request = CreationMaterialCreateRequest(
        kind="image",
        title="原创图片",
        image_data_base64=base64.b64encode(original).decode(),
        rights_statement="本人制作",
    )
    service = CreationService(repository)
    created = await service.create_material(OWNER, "image", request)
    edited = await service.save_material_revision(
        created.id,
        OWNER,
        "image-caption",
        CreationRevisionSaveRequest(
            expected_revision_id=created.current_revision.id,
            text="新图注",
            data={"alt": "白色图", "image_sha256": "bad"},
        ),
    )
    content, media_type = await repository.get_image(created.id, OWNER)
    assert content == original and media_type == "image/png"
    assert (
        edited.current_revision.data["image_sha256"]
        == created.current_revision.data["image_sha256"]
    )
    with pytest.raises(AppError):
        await service.create_material(
            OWNER,
            "broken-image",
            request.model_copy(
                update={"image_data_base64": base64.b64encode(b"bad").decode()}
            ),
        )


async def test_current_schema_reapply_preserves_creation_revisions_and_unknown_budget():
    sql = (Path(__file__).resolve().parents[3] / "sql/schema.sql").read_text()
    async with isolated_postgres_engine() as engine:
        await apply_schema(engine, sql)
        repository = CreationRepository(
            async_sessionmaker(engine, expire_on_commit=False)
        )
        created = await task(repository)
        worker = f"creation/{created.id}/1"
        await repository.claim_task(created.id, worker)
        await repository.mark_call_sent(created.id, worker)
        await repository.settle_call(created.id, worker, known=False)
        for _ in range(2):
            await apply_schema(engine, sql)
        preserved = await repository.get_task(created.id, OWNER)
        assert preserved.usage.calls_reserved == preserved.usage.unknown_operations == 1
        async with repository._sessions() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(CreationRevisionRow)
                )
                == 1
            )
