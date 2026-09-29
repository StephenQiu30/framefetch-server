"""Route durable inspection commands; other business events retain their transport."""

import asyncio
from datetime import timedelta

from temporalio.api.workflowservice.v1 import (
    DescribeNamespaceRequest,
    RegisterNamespaceRequest,
)
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from app.integrations.messaging import EventEnvelope, EventEnvelopeError
from app.repositories.downloads.intent_repository import IntentRepository
from app.services.downloads.intent_models import ACTIVE_INTENT_STATUSES
from app.workers.download.workflows import InspectionCommand, InspectionWorkflow
from app.workers.outbox.loop import EventPublisher


class CommandPublisher:
    def __init__(
        self,
        fallback: EventPublisher,
        intents: IntentRepository,
        *,
        address: str,
        namespace: str,
    ) -> None:
        self._fallback = fallback
        self._intents = intents
        self._address = address
        self._namespace = namespace
        self._client: Client | None = None

    async def publish(self, envelope: EventEnvelope) -> None:
        if envelope.event_type not in {
            "download.intent.requested",
            "download.intent.cancelled",
        }:
            await self._fallback.publish(envelope)
            return
        generation = envelope.payload.get("generation")
        if (
            set(envelope.payload) != {"intent_id", "generation"}
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
        if not cancel and state.status not in ACTIVE_INTENT_STATUSES:
            return  # Also protects against redelivery after Temporal history retention.
        if self._client is None:
            self._client = await connect_temporal(self._address, self._namespace)
        handle = self._client.get_workflow_handle(command.workflow_id)
        if cancel:
            try:
                await handle.cancel(rpc_timeout=timedelta(seconds=5))
            except RPCError as exc:
                if exc.status != RPCStatusCode.NOT_FOUND:
                    raise
            return
        binding = {"intent_id": command.intent_id, "generation": command.generation}
        try:
            await self._client.start_workflow(
                InspectionWorkflow.run,
                command,
                id=command.workflow_id,
                task_queue="ff-inspect",
                memo=binding,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
                rpc_timeout=timedelta(seconds=5),
            )
        except WorkflowAlreadyStartedError:
            description = await handle.describe(rpc_timeout=timedelta(seconds=5))
            if await description.memo() != binding:
                raise EventEnvelopeError(
                    "inspection workflow binding mismatch"
                ) from None


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
