"""Renewal failures cancel child calls and never consume a stranded model slot."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from app.core.config import Settings
from app.services.analysis_execution.content_models import ContentModelRequest
from app.services.analysis_execution.errors import AnalysisOutcomeUnknown
from app.services.analysis_execution.models import AnalysisStepBegin, AnalysisStepStatus
from app.services.analysis_execution.monitor import AnalysisLeaseMonitor
from app.workers.analysis import skill_activities
from app.workers.analysis.skill_activities import SkillActivities
from app.workers.analysis.skill_workflow import SkillCommand
from temporalio.exceptions import ApplicationError
from tests.unit.workers.analysis.fakes import NOW, running_job


@pytest.mark.parametrize("claim", [None, RuntimeError("private db failure")])
async def test_claim_none_or_error_releases_acquired_slot(monkeypatch, claim):
    monkeypatch.setattr(skill_activities.activity, "heartbeat", lambda: None)
    job = replace(
        running_job(),
        status="queued",
        input_kind="video",
        result_contract="structured-report",
    )
    repository = AsyncMock()
    repository.get_job.return_value = job
    if isinstance(claim, Exception):
        repository.claim_run.side_effect = claim
    else:
        repository.claim_run.return_value = None
    executor = AsyncMock()
    activities = SkillActivities(
        repository,
        AsyncMock(),
        {("video", "structured-report"): executor},
        Settings(app_env="test", _env_file=None),
    )
    command = SkillCommand(str(job.id), str(job.run_id), job.run_no)
    if isinstance(claim, Exception):
        with pytest.raises(ApplicationError):
            await activities.run(command)
    else:
        assert await activities.run(command) == "superseded"
    assert activities._model_slot._value == 1
    executor.execute.assert_not_awaited()


async def test_failed_renewal_cancels_active_call_without_logging_error_message(
    tmp_path, caplog
):
    repository = AsyncMock()
    repository.begin_step.return_value = AnalysisStepBegin(AnalysisStepStatus.NEW)
    repository.heartbeat.side_effect = [
        True,
        ConnectionError("secret credential body must not leak"),
    ]
    monitor = AnalysisLeaseMonitor(
        repository=repository,
        job_id=running_job().id,
        run_id=running_job().run_id,
        owner="worker",
        attempt=1,
        clock=lambda: NOW,
        lease_for=timedelta(seconds=60),
        interval=0.01,
    )
    called = 0
    cancelled = asyncio.Event()

    async def call():
        nonlocal called
        called += 1
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    request = ContentModelRequest(tmp_path, "source content", "{}", "a" * 64, "plan")
    with pytest.raises(AnalysisOutcomeUnknown):
        await monitor.step(
            "plan",
            request,
            call,
            lambda result: result,
            stage=skill_activities.AnalysisStage.ANALYZING,
            progress=20,
        )
    assert cancelled.is_set() and called == 1
    repository.complete_step.assert_not_awaited()
    repository.abandon_step.assert_not_awaited()
    assert "ConnectionError" in caplog.text
    assert "secret credential body" not in caplog.text
    # Re-entering a lost step observes the unknown journal; it cannot call again.
    repository.begin_step.return_value = AnalysisStepBegin(AnalysisStepStatus.UNKNOWN)
    with pytest.raises(AnalysisOutcomeUnknown):
        await monitor.step(
            "plan",
            request,
            call,
            lambda result: result,
            stage=skill_activities.AnalysisStage.ANALYZING,
            progress=20,
        )
    assert called == 1


async def test_binding_and_temporal_command_use_one_absolute_task_deadline():
    repository = AsyncMock()
    monitor = AnalysisLeaseMonitor(
        repository=repository,
        job_id=running_job().id,
        run_id=running_job().run_id,
        owner="worker",
        attempt=1,
        clock=lambda: NOW,
        lease_for=timedelta(seconds=60),
        interval=5,
        execution_deadline=NOW + timedelta(seconds=123),
    )
    await monitor.bind_execution(
        {"max_model_calls": 17}, deadline_for=timedelta(seconds=3000)
    )
    assert repository.bind_execution.call_args.kwargs["deadline"] == NOW + timedelta(
        seconds=123
    )
    assert monitor.bounded_timeout(600) == 123
    assert SkillCommand("job", "run", 1).timeout_seconds == 900


async def test_cancel_while_waiting_slot_has_no_claim_or_reserved_call(monkeypatch):
    monkeypatch.setattr(skill_activities.activity, "heartbeat", lambda: None)
    job = replace(
        running_job(),
        status="queued",
        input_kind="video",
        result_contract="structured-report",
    )
    repository = AsyncMock()
    repository.get_job.return_value = job
    repository.fail_run.return_value = replace(job, status="cancelled")
    activities = SkillActivities(
        repository,
        AsyncMock(),
        {("video", "structured-report"): AsyncMock()},
        Settings(app_env="test", _env_file=None),
    )
    await activities._model_slot.acquire()
    task = asyncio.create_task(
        activities.run(SkillCommand(str(job.id), str(job.run_id), job.run_no))
    )
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    repository.claim_run.assert_not_awaited()
    activities.persistence.begin_step.assert_not_awaited()
    assert activities._model_slot._value == 0
    activities._model_slot.release()


async def test_database_exception_code_is_not_persisted_as_business_error(monkeypatch):
    monkeypatch.setattr(skill_activities.activity, "heartbeat", lambda: None)
    job = replace(
        running_job(),
        status="queued",
        input_kind="video",
        result_contract="structured-report",
    )
    repository = AsyncMock()
    repository.get_job.return_value = job
    repository.claim_run.return_value = replace(job, status="running")

    class DatabaseFailure(Exception):
        code = "gkpj"

    executor = AsyncMock()
    executor.execute.side_effect = DatabaseFailure()
    activities = SkillActivities(
        repository,
        AsyncMock(),
        {("video", "structured-report"): executor},
        Settings(app_env="test", _env_file=None),
    )
    with pytest.raises(ApplicationError, match="Skill infrastructure unavailable"):
        await activities.run(SkillCommand(str(job.id), str(job.run_id), job.run_no))
    repository.fail_run.assert_not_awaited()
