"""Resolve retries preserve the deadline and require resource cleanup."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models.download_intent import DownloadIntentRow
from app.repositories.downloads.intent_repository import (
    IntentRepository,
    _expire_if_due,
)
from app.services.downloads.errors import (
    ApplicationError,
    ApplicationErrorCode,
    PersistenceConflict,
)
from app.services.downloads.inspection_models import EncryptedUrl
from app.services.downloads.intent_models import (
    IntentOperation,
    IntentSnapshot,
    IntentStatus,
)
from app.workers.download.activities import InspectionActivities
from app.workers.download.workflows import InspectionCommand

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def snapshot():
    return IntentSnapshot(
        uuid4(),
        "a" * 64,
        IntentStatus.QUEUED,
        0,
        NOW + timedelta(seconds=120),
        0,
        None,
        None,
        None,
        NOW,
        NOW,
    )


class Repository:
    def __init__(self):
        self.state = snapshot()
        self.claims = []

    async def claim(self, intent_id, generation, *, recover=False, **kwargs):
        if self.state.status is not IntentStatus.QUEUED and not (
            recover and self.state.status is IntentStatus.RESOLVING
        ):
            return None
        self.state = replace(
            self.state, status=IntentStatus.RESOLVING, version=self.state.version + 1
        )
        self.claims.append(self.state)
        return IntentOperation(self.state, EncryptedUrl(b"opaque", b"nonce", "test"))

    async def execution_state(self, *args):
        return self.state

    async def fail(self, operation, *, reason_code, **kwargs):
        return await self.complete(
            operation, None, status=IntentStatus.FAILED, reason_code=reason_code
        )

    async def complete(
        self,
        operation,
        result,
        *,
        status=IntentStatus.READY,
        reason_code=None,
        **kwargs,
    ):
        if (
            operation.version != self.state.version
            or self.state.status is not IntentStatus.RESOLVING
        ):
            raise PersistenceConflict
        self.state = replace(self.state, status=status, reason_code=reason_code)
        return self.state

    async def confirm_cancel(self, *args, **kwargs):
        if self.state.status is IntentStatus.CANCELLING:
            self.state = replace(self.state, status=IntentStatus.CANCELLED)
        return self.state


class Inspector:
    def __init__(self):
        self.calls = 0
        self.events = []
        self.error = None

    async def cancel(self, task_id):
        self.events.append(("cleanup", task_id))

    async def prepare(self, *args, task_id, deadline):
        self.calls += 1
        self.events.append(("inspect", task_id))
        if self.error is not None:
            raise self.error
        return object()


class Cipher:
    def decrypt(self, envelope):
        return "https://media.example/video"


async def test_worker_restart_reclaims_same_generation_after_old_runner_cleanup():
    repository, inspector = Repository(), Inspector()
    inspector.error = RuntimeError("non-public infrastructure details")
    activities = InspectionActivities(
        repository, inspector, Cipher(), clock=lambda: NOW
    )
    command = InspectionCommand(str(repository.state.id), 0)
    with pytest.raises(RuntimeError):
        await activities.execute(command)
    old = repository.claims[0]
    assert repository.state.status is IntentStatus.RESOLVING
    inspector.error = None
    assert (await activities.execute(command, recover=True)).status == "ready"
    current = repository.claims[1]
    assert current.version > old.version
    assert current.generation == old.generation and current.deadline == old.deadline
    assert (
        inspector.events
        == [("cleanup", command.task_id), ("inspect", command.task_id)] * 2
    )
    with pytest.raises(PersistenceConflict):
        await repository.complete(old, object())
    assert (await activities.execute(command, recover=True)).status == "ready"
    assert inspector.calls == 2


async def test_expected_media_failure_is_terminal_and_never_retried():
    repository, inspector = Repository(), Inspector()
    inspector.error = ApplicationError(ApplicationErrorCode.LOGIN_REQUIRED)
    activities = InspectionActivities(
        repository, inspector, Cipher(), clock=lambda: NOW
    )
    command = InspectionCommand(str(repository.state.id), 0)
    assert (await activities.execute(command)).status == "failed"
    assert repository.state.reason_code == "login_required"
    assert (await activities.execute(command, recover=True)).status == "failed"
    assert inspector.calls == 1


async def test_cancel_terminal_waits_for_runner_cleanup_acknowledgement():
    entered, cleanup_entered, cleaned = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    repository = Repository()

    class WaitingInspector(Inspector):
        async def prepare(self, *args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        async def cancel(self, task_id):
            if entered.is_set():
                cleanup_entered.set()
                await cleaned.wait()

    activities = InspectionActivities(
        repository, WaitingInspector(), Cipher(), clock=lambda: NOW
    )
    task = asyncio.create_task(
        activities.execute(InspectionCommand(str(repository.state.id), 0))
    )
    await entered.wait()
    repository.state = replace(
        repository.state,
        status=IntentStatus.CANCELLING,
        version=repository.state.version + 1,
    )
    task.cancel()
    await cleanup_entered.wait()
    assert repository.state.status is IntentStatus.CANCELLING
    cleaned.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert repository.state.status is IntentStatus.CANCELLED


async def test_cancel_ack_loss_keeps_request_pending():
    repository, inspector = Repository(), Inspector()
    entered = asyncio.Event()

    async def prepare(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    async def cancel(task_id):
        if entered.is_set():
            raise RuntimeError("acknowledgement lost")

    inspector.prepare, inspector.cancel = prepare, cancel
    activities = InspectionActivities(
        repository, inspector, Cipher(), clock=lambda: NOW
    )
    task = asyncio.create_task(
        activities.execute(InspectionCommand(str(repository.state.id), 0))
    )
    await entered.wait()
    repository.state = replace(
        repository.state,
        status=IntentStatus.CANCELLING,
        version=repository.state.version + 1,
    )
    task.cancel()
    with pytest.raises(RuntimeError, match="acknowledgement lost"):
        await task
    assert repository.state.status is IntentStatus.CANCELLING


def test_expiration_requests_cleanup_once_and_preserves_confirmed_results():
    row = DownloadIntentRow(status="resolving", deadline=NOW, version=1, updated_at=NOW)
    assert _expire_if_due(row, NOW)
    assert row.status == "cancelling" and row.version == 2
    assert not _expire_if_due(row, NOW + timedelta(seconds=1))
    for status in ("cancelled", "ready", "handed_off", "failed", "expired"):
        row.status = status
        assert not _expire_if_due(row, NOW)
        assert row.status == status and row.version == 2


class RowSession:
    def __init__(self, row):
        self.row = row
        self.events = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def begin(self):
        return self

    async def get(self, *args, **kwargs):
        return self.row

    def add(self, event):
        self.events.append(event)


async def test_repository_recovery_changes_version_without_resetting_deadline():
    row = DownloadIntentRow(
        id=uuid4(),
        owner_hash="a" * 64,
        status="resolving",
        version=1,
        deadline=NOW + timedelta(seconds=120),
        generation=0,
        created_at=NOW,
        updated_at=NOW,
        url_ciphertext=b"opaque",
        url_nonce=b"nonce",
        url_key_id="test",
    )
    session = RowSession(row)
    repo = IntentRepository(lambda: session)
    assert await repo.claim(row.id, 0, now=NOW) is None
    recovered = await repo.claim(row.id, 0, now=NOW, recover=True)
    assert recovered.intent.version == 2 and recovered.intent.deadline == row.deadline
    assert await repo.claim(row.id, 0, now=row.deadline, recover=True) is None
    assert row.status == "cancelling" and len(session.events) == 1
    assert (
        await repo.confirm_cancel(row.id, 0, now=row.deadline)
    ).status is IntentStatus.EXPIRED


@pytest.mark.parametrize("overdue", [0, 1])
async def test_zero_remaining_time_does_not_enter_prepare(overdue):
    repository, inspector = Repository(), Inspector()
    repository.state = replace(
        repository.state, deadline=NOW - timedelta(seconds=overdue)
    )
    activities = InspectionActivities(
        repository, inspector, Cipher(), clock=lambda: NOW
    )
    command = InspectionCommand(str(repository.state.id), 0)
    result = await activities.execute(command)
    assert result.status == "failed"
    assert repository.state.reason_code == "transient"
    assert inspector.calls == 0
    assert inspector.events == [("cleanup", command.task_id)] * 2
