"""Route durable inspection and Skill commands; other events keep their transport."""

import asyncio
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from temporalio.api.workflowservice.v1 import (
    DescribeNamespaceRequest,
    RegisterNamespaceRequest,
)
from temporalio.client import Client, WorkflowHandle
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from app.integrations.messaging import EventEnvelope, EventEnvelopeError
from app.repositories.downloads.intent_repository import IntentRepository
from app.services.analysis.models import AnalysisJobSnapshot
from app.services.downloads.intent_models import ACTIVE_INTENT_STATUSES
from app.workers.analysis.workflows import SKILL_TASK_QUEUE, SkillCommand, SkillWorkflow
from app.workers.download.workflows import InspectionCommand, InspectionWorkflow
from app.workers.outbox.loop import EventPublisher

_INSPECTION_EVENTS = {
    "download.intent.requested",
    "download.intent.cancelled",
    "download.intent.resumed",
}
_ACTIVE_ANALYSIS_STATUSES = {"queued", "running", "retry_wait"}
_RPC_TIMEOUT = timedelta(seconds=5)


class AnalysisJobReader(Protocol):
    async def get_job(self, job_id: UUID) -> AnalysisJobSnapshot | None: ...


class CommandPublisher:
    def __init__(
        self,
        fallback: EventPublisher,
        intents: IntentRepository,
        analyses: AnalysisJobReader,
        *,
        address: str,
        namespace: str,
    ) -> None:
        self._fallback = fallback
        self._intents = intents
        self._analyses = analyses
        self._address = address
        self._namespace = namespace
        self._client: Client | None = None

    async def publish(self, envelope: EventEnvelope) -> None:
        if envelope.event_type in _INSPECTION_EVENTS:
            await self._inspection(envelope)
        elif envelope.event_type == "analysis.requested":
            await self._skill(envelope)
        else:
            await self._fallback.publish(envelope)

    async def _inspection(self, envelope: EventEnvelope) -> None:
        resume = envelope.event_type == "download.intent.resumed"
        expected_fields = {"intent_id", "generation"} | (
            {"wait_id"} if resume else set()
        )
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
        if resume:
            authorization_id = envelope.payload.get("wait_id")
            if not isinstance(authorization_id, str):
                raise EventEnvelopeError("invalid inspection resume")
            try:
                requested_wait = UUID(authorization_id)
            except ValueError:
                raise EventEnvelopeError("invalid inspection resume") from None
            if state.authorization_id != requested_wait:
                return
        cancel = envelope.event_type == "download.intent.cancelled"
        if not cancel and state.status not in ACTIVE_INTENT_STATUSES:
            return  # Also protects against redelivery after Temporal history retention.
        client = await self._connect()
        handle = client.get_workflow_handle(command.workflow_id)
        if resume:
            await _require_binding(
                handle,
                {"intent_id": command.intent_id, "generation": command.generation},
                "inspection",
            )
            await handle.execute_update(
                InspectionWorkflow.resume,
                str(state.authorization_id),
                id=str(envelope.event_id),
                rpc_timeout=_RPC_TIMEOUT,
            )
            return
        if cancel:
            try:
                await handle.cancel(rpc_timeout=_RPC_TIMEOUT)
            except RPCError as exc:
                if exc.status != RPCStatusCode.NOT_FOUND:
                    raise
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

    async def _skill(self, envelope: EventEnvelope) -> None:
        payload = envelope.payload
        run_no = payload.get("run_no")
        if (
            set(payload) != {"job_id", "run_id", "run_no", "version"}
            or payload["job_id"] != str(envelope.aggregate_id)
            or not isinstance(payload["run_id"], str)
            or type(run_no) is not int
            or run_no < 1
        ):
            raise EventEnvelopeError("invalid analysis command")
        try:
            run_id = UUID(payload["run_id"])
        except ValueError:
            raise EventEnvelopeError("invalid analysis command") from None
        command = SkillCommand(str(envelope.aggregate_id), str(run_id), run_no)
        job = await self._analyses.get_job(envelope.aggregate_id)
        if (
            job is None
            or job.run_id != run_id
            or job.status not in _ACTIVE_ANALYSIS_STATUSES
        ):
            return  # Superseded, cancelled or finished; also after history retention.
        client = await self._connect()
        binding: dict[str, object] = {
            "job_id": command.job_id,
            "run_id": command.run_id,
            "run_no": command.run_no,
        }
        try:
            await client.start_workflow(
                SkillWorkflow.run,
                command,
                id=command.workflow_id,
                task_queue=SKILL_TASK_QUEUE,
                memo=binding,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
                rpc_timeout=_RPC_TIMEOUT,
            )
        except WorkflowAlreadyStartedError:
            handle = client.get_workflow_handle(command.workflow_id)
            await _require_binding(handle, binding, "skill")

    async def _connect(self) -> Client:
        if self._client is None:
            self._client = await connect_temporal(self._address, self._namespace)
        return self._client


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
