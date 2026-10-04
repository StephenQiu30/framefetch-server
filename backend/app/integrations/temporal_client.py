"""Route durable inspection and Skill commands; other events keep their transport."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from temporalio.api.workflowservice.v1 import (
    DescribeNamespaceRequest,
    RegisterNamespaceRequest,
)
from temporalio.client import Client, WorkflowFailureError, WorkflowHandle
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from app.integrations.messaging.envelope import EventEnvelope, EventEnvelopeError
from app.repositories.creation import CreationRepository
from app.repositories.downloads.intent_repository import IntentRepository
from app.services.downloads.intent_models import IntentStatus
from app.workers.analysis.creation_workflow import CreationCommand, CreationWorkflow
from app.workers.download.workflows import InspectionCommand, InspectionWorkflow
from app.workers.outbox.loop import EventPublisher

_INSPECTION_EVENTS = {
    "download.intent.requested",
    "download.intent.cancelled",
}
_RPC_TIMEOUT = timedelta(seconds=5)


class CommandPublisher:
    def __init__(
        self,
        fallback: EventPublisher,
        intents: IntentRepository,
        *,
        address: str,
        namespace: str,
        cancel_inspection: Callable[[str], Awaitable[None]],
        creation: CreationRepository | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._fallback = fallback
        self._intents = intents
        self._address = address
        self._namespace = namespace
        self._cancel_inspection = cancel_inspection
        self._creation = creation
        self._clock = clock
        self._client: Client | None = None

    async def publish(self, envelope: EventEnvelope) -> None:
        if envelope.event_type in _INSPECTION_EVENTS:
            await self._inspection(envelope)
        elif envelope.event_type == "analysis.requested":
            raise EventEnvelopeError("legacy analysis execution has been retired")
        elif envelope.event_type == "creation.requested":
            await self._creation_skill(envelope)
        else:
            await self._fallback.publish(envelope)

    async def _inspection(self, envelope: EventEnvelope) -> None:
        expected_fields = {"intent_id", "generation"}
        generation = envelope.payload.get("generation")
        if (
            set(envelope.payload) != expected_fields
            or envelope.payload["intent_id"] != str(envelope.aggregate_id)
            or type(generation) is not int
            or generation < 0
        ):
            raise EventEnvelopeError("invalid inspection command")
        command = InspectionCommand(str(envelope.aggregate_id), generation)
        state = await self._intents.execution_state(envelope.aggregate_id)
        if state.generation != generation:
            return
        cancel = envelope.event_type == "download.intent.cancelled"
        if not cancel and state.status not in {
            IntentStatus.QUEUED,
            IntentStatus.RESOLVING,
        }:
            return  # Also protects against redelivery after Temporal history retention.
        client = await self._connect()
        handle = client.get_workflow_handle(command.workflow_id)
        if cancel:
            if state.status != IntentStatus.CANCELLING:
                return
            try:
                await handle.cancel(rpc_timeout=_RPC_TIMEOUT)
                # Stop Workflow scheduling before cancelling its Runner resource.
                # An acknowledgement lost on either transport leaves the Outbox
                # unpublished so its ordinary redelivery retries confirmation.
                try:
                    async with asyncio.timeout(45):
                        await handle.result(rpc_timeout=_RPC_TIMEOUT)
                except WorkflowFailureError:
                    pass  # Any closed Workflow can no longer start the Activity.
            except RPCError as exc:
                if exc.status != RPCStatusCode.NOT_FOUND:
                    raise
            await self._cancel_inspection(command.task_id)
            await self._intents.confirm_cancel(
                envelope.aggregate_id, generation, now=self._clock()
            )
            return
        binding: dict[str, object] = {
            "intent_id": command.intent_id,
            "generation": command.generation,
        }
        try:
            await client.start_workflow(
                InspectionWorkflow.run,
                command,
                id=command.workflow_id,
                task_queue="ff-inspect",
                memo=binding,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
                rpc_timeout=_RPC_TIMEOUT,
            )
        except WorkflowAlreadyStartedError:
            await _require_binding(handle, binding, "inspection")

    async def _connect(self) -> Client:
        if self._client is None:
            self._client = await connect_temporal(self._address, self._namespace)
        return self._client

    async def _creation_skill(self, envelope: EventEnvelope) -> None:
        payload = envelope.payload
        attempt = payload.get("attempt")
        if (
            set(payload) != {"task_id", "attempt", "request_id"}
            or payload["task_id"] != str(envelope.aggregate_id)
            or type(attempt) is not int
            or attempt < 1
            or not isinstance(payload["request_id"], str)
        ):
            raise EventEnvelopeError("invalid creation command")
        if self._creation is None:
            raise EventEnvelopeError("creation execution is unavailable")
        task = await self._creation.get_task(envelope.aggregate_id)
        if task.status.value != "queued" or task.attempt != attempt:
            return
        command = CreationCommand(str(task.id), attempt)
        client = await self._connect()
        binding: dict[str, object] = {"task_id": command.task_id, "attempt": attempt}
        try:
            await client.start_workflow(
                CreationWorkflow.run,
                command,
                id=command.workflow_id,
                task_queue="ff-skill",
                memo=binding,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
                rpc_timeout=_RPC_TIMEOUT,
            )
        except WorkflowAlreadyStartedError:
            await _require_binding(
                client.get_workflow_handle(command.workflow_id), binding, "creation"
            )


async def _require_binding(
    handle: WorkflowHandle[object, object], binding: dict[str, object], kind: str
) -> None:
    description = await handle.describe(rpc_timeout=_RPC_TIMEOUT)
    if await description.memo() != binding:
        raise EventEnvelopeError(f"{kind} workflow binding mismatch") from None


async def connect_temporal(address: str, namespace: str) -> Client:
    """Idempotent workstation namespace initialization; no business DB dependency."""
    async with asyncio.timeout(10):
        client = await Client.connect(address, namespace=namespace)
        try:
            await client.workflow_service.describe_namespace(
                DescribeNamespaceRequest(namespace=namespace)
            )
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise
            request = RegisterNamespaceRequest(namespace=namespace)
            request.workflow_execution_retention_period.FromTimedelta(timedelta(days=7))
            try:
                await client.workflow_service.register_namespace(request)
            except RPCError as concurrent:
                if concurrent.status != RPCStatusCode.ALREADY_EXISTS:
                    raise
        return client
