"""One durable content-analysis attempt; lost paid calls never auto-repeat."""

from dataclasses import dataclass
from datetime import timedelta
from typing import cast

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError


@dataclass(frozen=True)
class CreationCommand:
    task_id: str
    attempt: int

    @property
    def workflow_id(self) -> str:
        return f"creation/{self.task_id}/{self.attempt}"


@workflow.defn
class CreationWorkflow:
    @workflow.run
    async def run(self, command: CreationCommand) -> str:
        try:
            result = await workflow.execute_activity(
                "run_creation",
                command,
                result_type=str,
                start_to_close_timeout=timedelta(hours=1),
                heartbeat_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )
            return cast(str, result)
        except ActivityError:
            result = await workflow.execute_activity(
                "reconcile_creation",
                command,
                result_type=str,
                start_to_close_timeout=timedelta(seconds=20),
                schedule_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=5),
            )
            return cast(str, result)
