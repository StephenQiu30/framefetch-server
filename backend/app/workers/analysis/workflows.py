"""Deterministic Skill run scheduling. Payloads contain business references only."""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, CancelledError, is_cancelled_exception

SKILL_TASK_QUEUE = "ff-skill"


@dataclass(frozen=True)
class SkillCommand:
    job_id: str
    run_id: str
    run_no: int

    @property
    def workflow_id(self) -> str:
        return f"skill/{self.job_id}/{self.run_no}"


@dataclass(frozen=True)
class SkillOutcome:
    status: str
    retry_at: float | None = None


@workflow.defn
class SkillWorkflow:
    @workflow.run
    async def run(self, command: SkillCommand) -> SkillOutcome:
        # Each Activity is one business attempt of the run. Temporal retries only
        # lost attempts; the step journal keeps those from repeating model calls.
        while True:
            try:
                result: SkillOutcome = await workflow.execute_activity(
                    "run_skill",
                    command,
                    result_type=SkillOutcome,
                    start_to_close_timeout=timedelta(hours=6),
                    heartbeat_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=5), maximum_attempts=3
                    ),
                    cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
                )
            except ActivityError as exc:
                if is_cancelled_exception(exc):
                    raise CancelledError() from None
                final: SkillOutcome = await workflow.execute_activity(
                    "finish_skill",
                    command,
                    result_type=SkillOutcome,
                    start_to_close_timeout=timedelta(seconds=10),
                    schedule_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=10),
                )
                return final
            if result.status != "retry_wait" or result.retry_at is None:
                return result
            await workflow.sleep(max(0, result.retry_at - workflow.now().timestamp()))
