"""One cancellable resolve Activity; Temporal owns its execution lifetime."""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@dataclass(frozen=True)
class InspectionCommand:
    intent_id: str
    generation: int

    @property
    def task_id(self) -> str:
        return f"parse_{self.intent_id.replace('-', '')}_{self.generation}"

    @property
    def workflow_id(self) -> str:
        return f"inspect/{self.intent_id}/{self.generation}"


@dataclass(frozen=True)
class InspectionOutcome:
    status: str
    inspection_id: str | None = None


@workflow.defn
class InspectionWorkflow:
    @workflow.run
    async def run(self, command: InspectionCommand) -> InspectionOutcome:
        result: InspectionOutcome = await workflow.execute_activity(
            "resolve",
            command,
            result_type=InspectionOutcome,
            start_to_close_timeout=timedelta(seconds=140),
            schedule_to_close_timeout=timedelta(seconds=160),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=10),
            ),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )

        return result
