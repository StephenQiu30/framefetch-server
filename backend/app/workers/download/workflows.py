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
    authorization_id: str | None = None
    authorization_deadline: float | None = None


@dataclass(frozen=True)
class InspectionWait:
    intent_id: str
    generation: int
    authorization_id: str


@workflow.defn
class InspectionWorkflow:
    def __init__(self) -> None:
        self._resumes: set[str] = set()

    @workflow.update
    async def resume(self, authorization_id: str) -> None:
        # A durable outbox command can arrive before the Activity reply. Retain
        # its wait identity so that this race never loses the user's action.
        self._resumes.add(authorization_id)

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
            if (
                result.status == "action_required"
                and result.authorization_id
                and result.authorization_deadline
            ):

                def resumed(wait_id: str | None = result.authorization_id) -> bool:
                    return wait_id is not None and wait_id in self._resumes

                try:
                    await workflow.wait_condition(
                        resumed,
                        timeout=timedelta(
                            seconds=max(
                                0,
                                result.authorization_deadline
                                - workflow.now().timestamp(),
                            )
                        ),
                    )
                    self._resumes.discard(result.authorization_id)
                except TimeoutError:
                    expired: InspectionOutcome = await workflow.execute_activity(
                        "expire_inspection_wait",
                        InspectionWait(
                            command.intent_id,
                            command.generation,
                            result.authorization_id,
                        ),
                        result_type=InspectionOutcome,
                        start_to_close_timeout=timedelta(seconds=10),
                        schedule_to_close_timeout=timedelta(minutes=5),
                        retry_policy=RetryPolicy(maximum_attempts=10),
                    )
                    if expired.status not in {"queued", "action_required"}:
                        return expired
                continue
            if result.status != "retry_wait" or result.retry_at is None:
                return result
            await workflow.sleep(max(0, result.retry_at - workflow.now().timestamp()))
