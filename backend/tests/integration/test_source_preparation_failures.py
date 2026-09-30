"""Static source failures must terminate before any actual platform attempt."""

from dataclasses import replace
from datetime import timedelta

import pytest
from app.models.download_intent import ResolutionAttemptRow
from app.services.downloads.resolution import ResolutionPlan
from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_failures import ProviderFailure
from tests.integration.test_download_intents import (
    NOW,
    OWNER,
    command,
    count,
    repository,
)
from tests.resolution import capability_for


@pytest.mark.parametrize(
    "code",
    ["credential_access_denied", "chrome_profile_unavailable", "source_read_failed"],
)
@pytest.mark.parametrize("bound_plan", [False, True])
async def test_static_source_failure_stops_preparing_despite_activity_retry_time(
    postgres_engine, code, bound_plan
):
    repo = repository(postgres_engine)
    accepted = await repo.accept(
        replace(command(), access_policy=ProviderAccessPolicy.PERSONAL_ENTITLED),
        now=NOW,
    )
    claimed = await repo.claim_preparation(accepted.id, 0, "source-read", now=NOW)
    preparing = claimed.intent
    if bound_plan:
        preparing = await repo.bind_plan(
            preparing,
            ResolutionPlan(capability_for(accepted.access_policy), 0),
            now=NOW,
        )
    failure = ProviderFailure.for_code(code)
    stopped = await repo.fail(
        preparing,
        now=NOW + timedelta(seconds=1),
        reason_code="provider_temporarily_unavailable",
        retry_at=NOW + timedelta(seconds=15),
        failure=failure,
    )
    assert stopped.status == "failed" and stopped.retry_at is None
    assert stopped.latest_failure == failure
    assert stopped.reason_code == "provider_temporarily_unavailable"
    assert stopped.deadline == accepted.deadline and stopped.generation == 0
    assert stopped.attempt == 0 and stopped.remaining_budget_ms == 180000
    assert await count(postgres_engine, ResolutionAttemptRow) == 0
    assert (
        await repo.claim_preparation(
            accepted.id, 0, "automatic-retry", now=NOW + timedelta(seconds=15)
        )
        is None
    )
    assert (await repo.get(accepted.id, OWNER)).status == "failed"


async def test_source_timeout_preparation_wait_keeps_the_original_intent_and_deadline(
    postgres_engine,
):
    repo = repository(postgres_engine)
    accepted = await repo.accept(
        replace(command(), access_policy=ProviderAccessPolicy.PERSONAL_ENTITLED),
        now=NOW,
    )
    for index in range(3):
        now = NOW + timedelta(seconds=index * 15)
        claimed = await repo.claim_preparation(accepted.id, 0, f"read-{index}", now=now)
        waiting = await repo.fail(
            claimed.intent,
            now=now,
            reason_code="provider_temporarily_unavailable",
            retry_at=now + timedelta(seconds=15),
            failure=ProviderFailure.for_code("source_read_timeout"),
        )
        assert waiting.status == "retry_wait"
        assert waiting.retry_at == now + timedelta(seconds=15)
        assert waiting.id == accepted.id and waiting.generation == 0
        assert waiting.deadline == accepted.deadline
        assert waiting.attempt == 0 and waiting.remaining_budget_ms == 180000
    assert (
        await repo.claim_preparation(
            accepted.id, 0, "after-deadline", now=accepted.deadline
        )
        is None
    )
    expired = await repo.get(accepted.id, OWNER)
    assert expired.status == "expired" and expired.generation == 0
    assert await count(postgres_engine, ResolutionAttemptRow) == 0
