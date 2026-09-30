"""Real PostgreSQL proof of single submission, immutable plans and budgets."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from app.models.download_intent import DownloadIntentRow, ResolutionAttemptRow
from app.repositories.errors import RepositoryConflict
from app.services.downloads.resolution import ResolutionPlan, operation_id
from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_failures import FailurePhase, ProviderFailure
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.integration.test_download_intents import (
    NOW,
    OWNER,
    command,
    inspection,
    repository,
)
from tests.resolution import capability_for, preparation_for, start_attempt


async def test_plan_is_committed_before_platform_claim_and_cannot_change(
    postgres_engine,
):
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    preparing = await repo.claim_preparation(accepted.id, 0, "prepare-one", now=NOW)
    assert preparing.intent.attempt == 0
    plan = ResolutionPlan(capability_for(accepted.access_policy), 0)
    bound = await repo.bind_plan(preparing.intent, plan, now=NOW)
    with pytest.raises(RepositoryConflict, match="immutable"):
        await repo.bind_plan(
            bound,
            replace(plan, capability=replace(plan.capability, revision="d" * 64)),
            now=NOW,
        )
    prepared = preparation_for(plan, bound.next_strategy_id)
    claims = await asyncio.gather(
        *(repo.begin_attempt(bound, prepared, now=NOW) for _ in range(30))
    )
    submitted = [item for item in claims if item is not None]
    assert len(submitted) == 1
    execution = submitted[0].execution
    assert execution.operation_id == operation_id(accepted.id, 0, 1)
    async with async_sessionmaker(postgres_engine)() as session:
        record = await session.scalar(select(ResolutionAttemptRow))
        assert record.status == "started" and record.plan_snapshot is not None
        assert record.context_key == prepared.context.generation_id
    duplicate = await repo.claim_preparation(
        accepted.id, 0, "another-delivery", now=NOW + timedelta(seconds=1)
    )
    assert not duplicate.newly_claimed and duplicate.intent.attempt == 1
    assert (await repo.running_operation(accepted.id, 0)).execution == execution


@pytest.mark.parametrize("changed", [False, True])
async def test_ordered_automatic_session_transition_requires_changed_evidence(
    postgres_engine, changed
):
    repo = repository(postgres_engine)
    accepted = await repo.accept(
        replace(command(), access_policy=ProviderAccessPolicy.OPERATOR_PUBLIC), now=NOW
    )
    first = await start_attempt(repo, accepted.id, 0, "first", now=NOW)
    next_step = await repo.fail(
        first.intent,
        now=NOW + timedelta(seconds=5),
        reason_code="provider_auth_required",
        failure=ProviderFailure.for_code(
            "credential_required", phase=FailurePhase.FETCH_METADATA
        ),
    )
    assert (
        next_step.status == "queued" and next_step.next_strategy_id == "yt-dlp-session"
    )
    second = await start_attempt(
        repo, accepted.id, 0, "second", now=NOW + timedelta(seconds=5)
    )
    waiting = await repo.fail(
        second.intent,
        now=NOW + timedelta(seconds=10),
        reason_code="provider_auth_required",
        failure=ProviderFailure.for_code("credential_required"),
    )
    assert waiting.status == "retry_wait" and waiting.attempt == 2
    assert waiting.retry_at == NOW + timedelta(seconds=25)
    assert (
        waiting.remaining_budget_ms == 170000 and waiting.deadline == accepted.deadline
    )
    third = await start_attempt(
        repo,
        accepted.id,
        0,
        "automatic-prepare",
        now=waiting.retry_at,
        credential="actually-changed" if changed else "fixture-session",
    )
    if not changed:
        assert third is None
        stopped = await repo.get(accepted.id, OWNER)
        assert stopped.status == "failed" and stopped.attempt == 2
        assert stopped.latest_failure == waiting.latest_failure
        return
    assert third.intent.attempt == 3 and third.intent.generation == 0
    ready = await repo.complete(
        third.intent, inspection(third.intent), now=waiting.retry_at
    )
    assert (
        ready.status == "ready"
        and ready.selected_operation_id == third.execution.operation_id
    )


async def test_effective_time_excludes_queue_and_backoff_but_never_resets(
    postgres_engine,
):
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    for number in range(3):
        started = NOW + timedelta(seconds=20 + number * 30)
        operation = await start_attempt(repo, accepted.id, 0, str(number), now=started)
        failed = await repo.fail(
            operation.intent,
            now=started + timedelta(seconds=10),
            reason_code="provider_temporarily_unavailable",
            failure=ProviderFailure.for_code("network_transient"),
        )
        assert failed.remaining_budget_ms == 180000 - (number + 1) * 10000
    assert failed.status == "failed" and failed.attempt == 3
    async with async_sessionmaker(postgres_engine)() as session:
        attempts = (
            await session.scalars(
                select(ResolutionAttemptRow).order_by(ResolutionAttemptRow.attempt_no)
            )
        ).all()
        assert (
            len(attempts) == 3 and sum(item.duration_ms for item in attempts) == 30000
        )
    refreshed = await repo.refresh(accepted.id, OWNER, now=NOW + timedelta(minutes=5))
    assert (
        refreshed.generation == 1
        and refreshed.attempt == 0
        and refreshed.remaining_budget_ms == 180000
    )
    assert refreshed.resolution_plan is None
    fourth = await start_attempt(
        repo, accepted.id, 1, "new-generation", now=NOW + timedelta(minutes=5)
    )
    assert fourth.execution.operation_id != attempts[0].operation_id


async def test_lost_execution_is_unknown_and_cancelled_completion_is_fenced(
    postgres_engine,
):
    repo = repository(postgres_engine)
    accepted = await repo.accept(command(), now=NOW)
    operation = await start_attempt(repo, accepted.id, 0, "first", now=NOW)
    cancelled = await repo.cancel(accepted.id, OWNER, now=NOW + timedelta(seconds=3))
    assert cancelled.attempt == 1 and cancelled.remaining_budget_ms == 177000
    with pytest.raises(RepositoryConflict):
        await repo.complete(
            operation.intent,
            inspection(operation.intent),
            now=NOW + timedelta(seconds=4),
        )
    async with async_sessionmaker(postgres_engine)() as session:
        record = await session.get(
            ResolutionAttemptRow, operation.execution.operation_id
        )
        assert record.status == "outcome_unknown"
    await repo.abandon_attempt(operation.intent, now=NOW + timedelta(seconds=4))
    async with async_sessionmaker(postgres_engine)() as session:
        record = await session.get(
            ResolutionAttemptRow, operation.execution.operation_id
        )
        assert record.status == "abandoned"
        row = await session.get(DownloadIntentRow, accepted.id)
        await session.delete(row)
        await session.commit()
        assert (
            await session.scalar(
                select(ResolutionAttemptRow).where(
                    ResolutionAttemptRow.operation_id
                    == operation.execution.operation_id
                )
            )
            is None
        )
