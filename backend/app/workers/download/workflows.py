"""Deterministic inspection scheduling. Payloads contain business references only."""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, CancelledError, is_cancelled_exception


@dataclass(frozen=True)
class InspectionCommand:
    intent_id: str
    generation: int

    @property
    def workflow_id(self) -> str:
        return f"inspect/{self.intent_id}/{self.generation}"


@dataclass(frozen=True)
class InspectionOutcome:
    status: str
    inspection_id: str | None = None
    retry_at: float | None = None


@workflow.defn
class InspectionWorkflow:
    @workflow.run
    async def run(self, command: InspectionCommand) -> InspectionOutcome:
        # Each invocation is a single inspection attempt. Database writes fence
        # stale invocations; only Temporal schedules subsequent attempts.
        while True:
            try:
                result: InspectionOutcome = await workflow.execute_activity(
                    "inspect_media",
                    command,
                    result_type=InspectionOutcome,
                    start_to_close_timeout=timedelta(seconds=260),
                    schedule_to_close_timeout=timedelta(seconds=280),
                    heartbeat_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
                )
            except ActivityError as exc:
                if is_cancelled_exception(exc):
                    raise CancelledError() from None
                result = await workflow.execute_activity(
                    "finish_inspection",
                    command,
                    result_type=InspectionOutcome,
                    start_to_close_timeout=timedelta(seconds=45),
                    schedule_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=10),
                )
            if result.status == "queued":
                continue
            if result.status != "retry_wait" or result.retry_at is None:
                return result
            await workflow.sleep(max(0, result.retry_at - workflow.now().timestamp()))
