"""One durable built-in Skill run; uncertain model calls are never repeated."""

from dataclasses import dataclass
from datetime import timedelta
from typing import cast

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError


@dataclass(frozen=True)
class SkillCommand:
    job_id: str
    run_id: str
    run_no: int
    timeout_seconds: float = 900

    @property
    def workflow_id(self) -> str:
        return f"skill/{self.job_id}/{self.run_id}/{self.run_no}"


@workflow.defn
class SkillWorkflow:
    @workflow.run
    async def run(self, command: SkillCommand) -> str:
        try:
            return cast(
                str,
                await workflow.execute_activity(
                    "run_analysis_skill",
                    command,
                    result_type=str,
                    start_to_close_timeout=timedelta(seconds=command.timeout_seconds),
                    heartbeat_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
                ),
            )
        except ActivityError:
            return cast(
                str,
                await workflow.execute_activity(
                    "reconcile_analysis_skill",
                    command,
                    result_type=str,
                    start_to_close_timeout=timedelta(seconds=20),
                    schedule_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=5),
                ),
            )
