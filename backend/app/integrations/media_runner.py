"""HMAC-authenticated client for the isolated Media Runner service."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.integrations.media_inspection_pipeline import (
    MediaInspectionPipeline,
    SessionPolicyReader,
)
from app.integrations.media_runner_models import (
    MediaRunnerClientError,
    RunnerArtifact,
    RunnerProgress,
    download_stage,
)
from app.schemas.engine_catalog import EngineCatalogResponse
from app.schemas.resolution import RunnerEngineCatalogResponse
from app.services.downloads.errors import (
    MediaInspectionAuthRequired,
    MediaInspectionContentRestricted,
    MediaInspectionDrmProtected,
    MediaInspectionDurationLimitExceeded,
    MediaInspectionFailure,
    MediaInspectionFormatUnavailable,
    MediaInspectionGeoRestricted,
    MediaInspectionLinkUnavailable,
    MediaInspectionMediaUnsupported,
    MediaInspectionPaidContentRestricted,
    MediaInspectionPolicyNotAllowed,
    MediaInspectionRateLimited,
    MediaInspectionSessionExpired,
    MediaInspectionSessionNotReady,
    MediaInspectionTemporarilyUnavailable,
    MediaInspectionTimeout,
    MediaInspectionUnsupported,
    MediaInspectionVerificationFailed,
)
from app.services.downloads.inspection_models import RunnerFormat, RunnerInspection
from app.services.downloads.resolution import (
    ResolutionCapability,
    ResolutionExecution,
    ResolutionPlan,
    ResolutionPreparation,
)
from app.services.downloads.rules.content_restrictions import ContentRestriction
from app.services.downloads.rules.enums import MediaKind
from app.services.downloads.rules.formats import DownloadPlan
from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_failures import (
    FailureEvidenceKind,
    FailurePhase,
    FailureScope,
    ProviderFailure,
    parse_retry_after,
)
from app.services.provider_route_admission import (
    ProviderRouteAdmission,
    RouteAdmissionUnavailable,
    RouteCoolingDown,
    RouteProbeTimeout,
)
from app.services.provider_types import ProviderAccessContextRef, ProviderAccessMode
from app.workers.runner.contracts import (
    CancelCommand,
    CancelResponse,
    DownloadPlanContract,
    DownloadRequest,
    DownloadResponse,
    InspectionOperationResponse,
    InspectRequest,
    InspectResponse,
    ProviderAccessContextContract,
    ProviderContextRequest,
    ProviderContextsRequest,
    ProviderContextsResponse,
    RunnerErrorContract,
    RuntimeResponse,
    TaskStatusResponse,
)
from app.workers.runner.provider_registry import (
    provider_profile,
    provider_profile_for_key,
)
from app.workers.runner.signing import sign_request

_TASK_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_CONTEXT_TIMEOUT_SECONDS = 30.0
logger = logging.getLogger(__name__)

_STATUS_CONTEXT_TIMEOUT_SECONDS = 0.25
ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class MediaRunnerClient(Protocol):
    """Runner strategy used by the routing facade."""

    async def engine_catalog(self) -> EngineCatalogResponse: ...

    async def resolution_capability(self, url: str) -> ResolutionCapability: ...

    async def prepare_resolution(
        self, url: str, plan: ResolutionPlan, strategy_id: str
    ) -> ResolutionPreparation: ...

    async def reconcile_inspection(
        self, url: str, execution: ResolutionExecution
    ) -> RunnerInspection: ...

    async def cancel_inspection(self, execution: ResolutionExecution) -> bool: ...

    async def context(
        self,
        url: str,
        *,
        access_mode: ProviderAccessMode | None = None,
        strategy_id: str | None = None,
        plan_revision: str | None = None,
    ) -> ProviderAccessContextRef: ...

    async def contexts_for_providers(
        self,
        provider_keys: tuple[str, ...],
        *,
        access_mode: ProviderAccessMode | None = None,
    ) -> tuple[ProviderAccessContextRef, ...]: ...

    async def inspect(
        self,
        url: str,
        *,
        access_mode: ProviderAccessMode | None = None,
        execution: ResolutionExecution | None = None,
    ) -> RunnerInspection: ...

    async def download(
        self,
        task_id: str,
        url: str,
        plan: DownloadPlan | None,
        *,
        expected_provider_media_id: str,
        expected_extractor_key: str,
        access_context: ProviderAccessContextRef,
        media_kind: MediaKind = MediaKind.VIDEO,
        asset_count: int = 0,
    ) -> RunnerArtifact: ...

    async def status(self, task_id: str) -> RunnerProgress: ...

    async def cancel(self, task_id: str) -> None: ...

    async def close(self) -> None: ...


class MediaRunnerHttpClient:
    def __init__(
        self,
        *,
        base_url: str,
        secret: bytes,
        workspace_root: Path,
        inspect_timeout_seconds: float,
        download_timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], int] | None = None,
        nonce: Callable[[], str] | None = None,
        admission: ProviderRouteAdmission | None = None,
        expected_access_mode: ProviderAccessMode | None = None,
    ) -> None:
        if len(secret) < 32:
            raise ValueError("runner HMAC secret must contain at least 32 bytes")
        self._secret = secret
        self._workspace_root = workspace_root.resolve()
        self._inspect_timeout = inspect_timeout_seconds
        self._download_timeout = download_timeout_seconds
        self._clock = clock or (lambda: int(time.time()))
        self._nonce = nonce or (lambda: secrets.token_urlsafe(24))
        self._owns_client = client is None
        self._admission = admission
        self._expected_access_mode = expected_access_mode
        self._client = client or httpx.AsyncClient(base_url=base_url)

    async def engine_catalog(self) -> EngineCatalogResponse:
        snapshot = await self._resolution_catalog()
        return EngineCatalogResponse.model_validate(
            snapshot.model_dump(exclude={"resolution_capabilities"})
        )

    async def _resolution_catalog(self) -> RunnerEngineCatalogResponse:
        return await self._request(
            "GET",
            "/internal/engine-catalog",
            b"",
            RunnerEngineCatalogResponse,
            15.0,
            timeout_code="engine_catalog_unavailable",
        )

    async def resolution_capability(self, url: str) -> ResolutionCapability:
        provider_key = provider_profile(url).key
        snapshot = await self._resolution_catalog()
        matches = tuple(
            item
            for item in snapshot.resolution_capabilities
            if item.provider_key == provider_key
        )
        if len(matches) != 1:
            raise MediaInspectionUnsupported
        return matches[0]

    async def prepare_resolution(
        self, url: str, plan: ResolutionPlan, strategy_id: str
    ) -> ResolutionPreparation:
        try:
            strategy = plan.strategy(strategy_id)
            context = await self.context(
                url,
                access_mode=strategy.access_mode,
                strategy_id=strategy_id,
                plan_revision=plan.revision,
            )
            if (
                context.strategy_id != strategy_id
                or context.adapter_revision != strategy.adapter_revision
            ):
                raise MediaRunnerClientError("context_changed", 409)
            runtime = await self._request(
                "GET",
                "/internal/runtime",
                b"",
                RuntimeResponse,
                5.0,
                timeout_code="runner_unavailable",
            )
            return ResolutionPreparation(context, runtime.instance_id)
        except MediaRunnerClientError as exc:
            raise _inspection_error(exc, before_media_io=True) from exc

    async def context(
        self,
        url: str,
        *,
        access_mode: ProviderAccessMode | None = None,
        strategy_id: str | None = None,
        plan_revision: str | None = None,
    ) -> ProviderAccessContextRef:
        provider_key = provider_profile(url).key
        response = await self._request(
            "POST",
            "/internal/context",
            ProviderContextRequest(
                url=url,
                access_mode=access_mode,
                strategy_id=strategy_id,
                plan_revision=plan_revision,
            )
            .model_dump_json(exclude_none=True)
            .encode(),
            ProviderAccessContextContract,
            min(self._inspect_timeout, _CONTEXT_TIMEOUT_SECONDS),
            timeout_code="inspection_timeout",
        )
        context = _context_to_domain(response)
        expected_mode = access_mode or (
            provider_profile_for_key(provider_key).initial_access_mode
            if self._expected_access_mode is ProviderAccessMode.OPERATOR_MANAGED
            else self._expected_access_mode
        )
        if (
            context.provider_key != provider_key
            or (expected_mode is not None and context.access_mode is not expected_mode)
            or (strategy_id is not None and context.strategy_id != strategy_id)
        ):
            raise MediaRunnerClientError("client_context_mismatch", 502)
        return context

    async def contexts_for_providers(
        self,
        provider_keys: tuple[str, ...],
        *,
        access_mode: ProviderAccessMode | None = None,
    ) -> tuple[ProviderAccessContextRef, ...]:
        response = await self._request(
            "POST",
            "/internal/contexts",
            ProviderContextsRequest(
                provider_keys=list(provider_keys), access_mode=access_mode
            )
            .model_dump_json(exclude_none=True)
            .encode(),
            ProviderContextsResponse,
            min(self._inspect_timeout, _STATUS_CONTEXT_TIMEOUT_SECONDS),
            timeout_code="inspection_timeout",
        )
        return tuple(_context_to_domain(context) for context in response.contexts)

    async def inspect(
        self,
        url: str,
        *,
        access_mode: ProviderAccessMode | None = None,
        execution: ResolutionExecution | None = None,
    ) -> RunnerInspection:
        context_ready = False
        context = None
        try:
            context = (
                execution.context
                if execution is not None
                else await self.context(url, access_mode=access_mode)
            )
            if execution is None:
                capability = await self.resolution_capability(url)
                revision = capability.revision
            else:
                revision = execution.plan_revision
            context_ready = context is not None
            if self._admission is None:
                response = await self._inspect_response(
                    url,
                    context,
                    execution.deadline_at if execution else None,
                    plan_revision=revision,
                    execution=execution,
                )
            else:
                assert context is not None
                response = await self._admission.run(
                    context,
                    lambda deadline: self._inspect_response(
                        url,
                        context,
                        min(deadline, execution.deadline_at)
                        if execution and deadline
                        else (execution.deadline_at if execution else deadline),
                        plan_revision=revision,
                        execution=execution,
                    ),
                )
        except RouteCoolingDown as exc:
            raise MediaInspectionRateLimited(retry_at=exc.retry_at) from exc
        except RouteProbeTimeout as exc:
            raise MediaInspectionTimeout from exc
        except RouteAdmissionUnavailable as exc:
            raise MediaInspectionTemporarilyUnavailable from exc
        except MediaRunnerClientError as exc:
            if execution is not None and (
                exc.failure is not None
                and exc.failure.evidence_kind is FailureEvidenceKind.TRANSPORT
                or exc.code == "invalid_runner_response"
            ):
                return await self.reconcile_inspection(url, execution)
            raise _inspection_error(exc, before_media_io=not context_ready) from exc
        return _inspection_result(response)

    async def cancel_inspection(self, execution: ResolutionExecution) -> bool:
        try:
            receipt = await self._request(
                "POST",
                f"/internal/inspection-operations/{execution.operation_id}/cancel",
                CancelCommand().model_dump_json().encode(),
                InspectionOperationResponse,
                25.0,
                timeout_code="runner_unavailable",
                runtime_instance_id=execution.runner_instance_id,
            )
        except MediaRunnerClientError:
            return False
        return receipt.status in {"succeeded", "failed", "cancelled"}

    async def reconcile_inspection(
        self, url: str, execution: ResolutionExecution
    ) -> RunnerInspection:
        try:
            target = f"/internal/inspection-operations/{execution.operation_id}"
            while True:
                receipt = await self._request(
                    "GET",
                    target,
                    b"",
                    InspectionOperationResponse,
                    5.0,
                    timeout_code="runner_unavailable",
                    runtime_instance_id=execution.runner_instance_id,
                )
                remaining = (execution.deadline_at - datetime.now(UTC)).total_seconds()
                if receipt.status != "active" or remaining <= 0:
                    break
                # Local receipt polling consumes no new platform call. A lost
                # ACK or duplicate delivery must not cancel a healthy owner.
                await asyncio.sleep(min(1, remaining))
            if receipt.status == "active":
                receipt = await self._request(
                    "POST",
                    f"{target}/cancel",
                    CancelCommand().model_dump_json().encode(),
                    InspectionOperationResponse,
                    25.0,
                    timeout_code="runner_unavailable",
                    runtime_instance_id=execution.runner_instance_id,
                )
            if receipt.result is not None:
                self._validate_inspection_context(receipt.result, execution.context)
                return _inspection_result(receipt.result)
            if receipt.status == "failed" and receipt.failure is not None:
                fact = receipt.failure.to_domain()
                raise MediaRunnerClientError(
                    fact.code, 502, failure=fact, retry_at=fact.retry_after
                )
            if receipt.status == "cancelled":
                fact = ProviderFailure.for_code(
                    "inspection_timeout", evidence_kind=FailureEvidenceKind.TRANSPORT
                )
                raise MediaRunnerClientError(fact.code, 504, failure=fact)
        except MediaRunnerClientError as exc:
            if exc.code not in {
                "runner_restarted",
                "runner_unavailable",
                "invalid_runner_response",
            }:
                raise _inspection_error(exc, before_media_io=False) from exc
        fact = ProviderFailure.for_code(
            "outcome_unknown", evidence_kind=FailureEvidenceKind.RUNTIME
        ).with_context(
            strategy_id=execution.strategy_id,
            context_key=execution.context.generation_id,
        )
        raise MediaInspectionTemporarilyUnavailable(failure=fact)

    @staticmethod
    def _validate_inspection_context(
        response: InspectResponse, context: ProviderAccessContextRef
    ) -> None:
        if _context_to_domain(response.access_context) != context:
            raise MediaRunnerClientError("client_context_mismatch", 422)
        if not response.options:
            raise MediaRunnerClientError("format_unavailable", 422)

    async def _inspect_response(
        self,
        url: str,
        context: ProviderAccessContextRef,
        deadline_at: datetime | None = None,
        *,
        plan_revision: str,
        execution: ResolutionExecution | None = None,
    ) -> InspectResponse:
        if context.strategy_id is None:
            raise MediaRunnerClientError("client_context_mismatch", 422)
        response = await self._request(
            "POST",
            "/internal/inspect",
            InspectRequest(
                url=url,
                access_context=ProviderAccessContextContract.from_domain(context),
                deadline_at=deadline_at,
                strategy_id=context.strategy_id,
                plan_revision=plan_revision,
                operation_id=execution.operation_id if execution else None,
            )
            .model_dump_json()
            .encode(),
            InspectResponse,
            self._inspect_timeout,
            timeout_code="inspection_timeout",
            runtime_instance_id=execution.runner_instance_id if execution else None,
        )
        self._validate_inspection_context(response, context)
        return response

    async def download(
        self,
        task_id: str,
        url: str,
        plan: DownloadPlan | None,
        *,
        expected_provider_media_id: str,
        expected_extractor_key: str,
        access_context: ProviderAccessContextRef,
        media_kind: MediaKind = MediaKind.VIDEO,
        asset_count: int = 0,
    ) -> RunnerArtifact:
        self._validate_task_id(task_id)
        body = (
            DownloadRequest(
                task_id=task_id,
                url=url,
                expected_provider_media_id=expected_provider_media_id,
                expected_extractor_key=expected_extractor_key,
                plan=(None if plan is None else DownloadPlanContract.from_domain(plan)),
                media_kind=media_kind,
                asset_count=asset_count,
                access_context=ProviderAccessContextContract.from_domain(
                    access_context
                ),
            )
            .model_dump_json()
            .encode()
        )

        async def execute(_deadline: datetime | None = None) -> DownloadResponse:
            return await self._request(
                "POST",
                "/internal/download",
                body,
                DownloadResponse,
                self._download_timeout,
                timeout_code="download_timeout",
            )

        async def probe(deadline: datetime | None) -> InspectResponse:
            capability = await self.resolution_capability(url)
            return await self._inspect_response(
                url, access_context, deadline, plan_revision=capability.revision
            )

        response = (
            await execute()
            if self._admission is None
            else await self._admission.run(
                access_context,
                execute,
                owner=task_id,
                probe=probe,
            )
        )
        workspace = Path(response.workspace_path).resolve()
        artifact = (workspace / response.artifact.relative_path).resolve()
        outside_root = not workspace.is_relative_to(self._workspace_root)
        outside_workspace = not artifact.is_relative_to(workspace)
        if outside_root or outside_workspace:
            raise MediaRunnerClientError("invalid_artifact_path", 502)
        return RunnerArtifact(
            task_id=response.task_id,
            workspace=workspace,
            artifact=artifact,
            size_bytes=response.artifact.size_bytes,
            sha256=response.artifact.sha256,
            duration_seconds=response.artifact.duration_seconds,
            container=response.artifact.container.value,
            video_streams=response.artifact.video_streams,
            audio_streams=response.artifact.audio_streams,
            media_kind=response.artifact.media_kind,
            asset_count=response.artifact.asset_count,
        )

    async def status(self, task_id: str) -> RunnerProgress:
        self._validate_task_id(task_id)
        response = await self._request(
            "GET",
            f"/internal/tasks/{task_id}",
            b"",
            TaskStatusResponse,
            self._inspect_timeout,
            timeout_code="runner_unavailable",
        )
        return RunnerProgress(download_stage(response.stage), response.progress)

    async def cancel(self, task_id: str) -> None:
        self._validate_task_id(task_id)
        await self._request(
            "POST",
            f"/internal/tasks/{task_id}/cancel",
            CancelCommand().model_dump_json().encode(),
            CancelResponse,
            self._inspect_timeout,
            timeout_code="runner_unavailable",
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        target: str,
        body: bytes,
        model: type[ResponseModel],
        timeout: float,
        *,
        timeout_code: str,
        runtime_instance_id: str | None = None,
    ) -> ResponseModel:
        instance_id = runtime_instance_id
        if instance_id is None and target in {
            "/internal/inspect",
            "/internal/download",
        }:
            # Bind this one execution, never transparently replay it after a boot.
            runtime = await self._request(
                "GET",
                "/internal/runtime",
                b"",
                RuntimeResponse,
                min(timeout, 5.0),
                timeout_code=timeout_code,
            )
            instance_id = runtime.instance_id
        timestamp, nonce = self._clock(), self._nonce()
        headers = {
            "Content-Type": "application/json",
            "X-Runner-Timestamp": str(timestamp),
            "X-Runner-Nonce": nonce,
            "X-Runner-Signature": sign_request(
                self._secret,
                method,
                target,
                body,
                timestamp,
                nonce,
                runtime_instance_id=instance_id,
            ),
        }
        if instance_id is not None:
            headers["X-Runner-Instance"] = instance_id
        try:
            response = await self._client.request(
                method,
                target,
                content=body,
                headers=headers,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise MediaRunnerClientError(
                timeout_code,
                504,
                failure=ProviderFailure.for_code(
                    timeout_code,
                    phase=_request_phase(target),
                    scope=FailureScope.RUNTIME,
                    evidence_kind=FailureEvidenceKind.TRANSPORT,
                ),
            ) from exc
        except httpx.HTTPError as exc:
            raise MediaRunnerClientError(
                "runner_unavailable",
                503,
                failure=ProviderFailure.for_code(
                    "runner_unavailable",
                    phase=_request_phase(target),
                    evidence_kind=FailureEvidenceKind.TRANSPORT,
                ),
            ) from exc
        if response.is_error:
            failure = _response_failure(response, phase=_request_phase(target))
            raise MediaRunnerClientError(
                failure.code,
                response.status_code,
                retry_at=failure.retry_after,
                failure=failure,
            )
        try:
            return model.model_validate_json(response.content)
        except ValidationError as exc:
            raise MediaRunnerClientError("invalid_runner_response", 502) from exc

    @staticmethod
    def _validate_task_id(task_id: str) -> None:
        if _TASK_ID.fullmatch(task_id) is None:
            raise ValueError("invalid runner task id")


def _inspection_result(response: InspectResponse) -> RunnerInspection:
    return RunnerInspection(
        extractor_key=response.media.extractor_key,
        provider_media_id=response.media.provider_media_id,
        title=response.media.title,
        duration_seconds=math.ceil(response.media.duration_seconds),
        formats=tuple(
            RunnerFormat(
                item.label,
                None if item.plan is None else item.plan.to_domain(),
                item.media_kind,
                item.asset_count,
            )
            for item in response.options
        ),
        access_context=_context_to_domain(response.access_context),
        thumbnail_data_url=response.media.thumbnail_data_url,
        media_kind=response.media.media_kind,
        asset_count=response.media.asset_count,
    )


class MediaRunnerRouter:
    """Route online media exclusively through the deployment session Runner."""

    def __init__(
        self, session: MediaRunnerClient, *, session_routes: SessionPolicyReader
    ) -> None:
        self._session = session
        self._inspection_pipeline = MediaInspectionPipeline(
            session, session_routes=session_routes
        )
        self._active: dict[str, MediaRunnerClient] = {}

    async def resolve_access_policy(
        self, url: str, requested: ProviderAccessPolicy | None = None
    ) -> ProviderAccessPolicy:
        return await self._inspection_pipeline.resolve_access_policy(url, requested)

    async def engine_catalog(self) -> EngineCatalogResponse:
        return await self._session.engine_catalog()

    async def resolution_capability(
        self, url: str, *, access_policy: ProviderAccessPolicy
    ) -> ResolutionCapability:
        try:
            selected = await self.resolve_access_policy(url, access_policy)
            capability = await self._session.resolution_capability(url)
            if capability.access_policy != selected:
                raise MediaInspectionPolicyNotAllowed
            return capability
        except MediaRunnerClientError as exc:
            raise _inspection_error(exc, before_media_io=True) from exc

    async def prepare_resolution(
        self, url: str, plan: ResolutionPlan, strategy_id: str
    ) -> ResolutionPreparation:
        return await self._session.prepare_resolution(url, plan, strategy_id)

    async def reconcile_inspection(
        self, url: str, execution: ResolutionExecution
    ) -> RunnerInspection:
        return await self._session.reconcile_inspection(url, execution)

    async def cancel_inspection(self, execution: ResolutionExecution) -> bool:
        return await self._session.cancel_inspection(execution)

    async def inspect(
        self,
        url: str,
        *,
        access_policy: ProviderAccessPolicy | None = None,
        execution: ResolutionExecution | None = None,
    ) -> RunnerInspection:
        return await self._inspection_pipeline.inspect(
            url, access_policy=access_policy, execution=execution
        )

    async def context(
        self, url: str, access_mode: ProviderAccessMode
    ) -> ProviderAccessContextRef:
        client = self._client_for_mode(provider_profile(url).key, access_mode)
        if client is None:
            raise MediaRunnerClientError("credential_required", 422)
        context = await client.context(url, access_mode=access_mode)
        if context.access_mode is not access_mode:
            raise MediaRunnerClientError("client_context_mismatch", 502)
        return context

    async def contexts_for_providers(
        self,
        requested: Mapping[str, ProviderAccessMode],
    ) -> Mapping[str, ProviderAccessContextRef]:
        groups = [
            (self._session, (key,), mode)
            for key, mode in requested.items()
            if self._client_for_mode(key, mode) is not None
        ]

        async def resolve(
            client: MediaRunnerClient,
            keys: tuple[str, ...],
            mode: ProviderAccessMode,
        ) -> tuple[ProviderAccessContextRef, ...]:
            try:
                return await client.contexts_for_providers(keys, access_mode=mode)
            except MediaRunnerClientError as exc:
                # provider_session_not_ready is an expected, actionable state;
                # anything else (timeouts, transport) deserves a trace.
                logger.log(
                    logging.INFO
                    if exc.code == "provider_session_not_ready"
                    else logging.WARNING,
                    "provider context unavailable providers=%s code=%s",
                    ",".join(keys),
                    exc.code,
                )
                return ()

        batches = await asyncio.gather(
            *(resolve(client, keys, mode) for client, keys, mode in groups)
        )
        contexts = {
            context.provider_key: context
            for batch in batches
            for context in batch
            if requested.get(context.provider_key) is context.access_mode
        }
        return contexts

    async def download(
        self,
        task_id: str,
        url: str,
        plan: DownloadPlan | None,
        *,
        expected_provider_media_id: str,
        expected_extractor_key: str,
        access_context: ProviderAccessContextRef,
        media_kind: MediaKind = MediaKind.VIDEO,
        asset_count: int = 0,
    ) -> RunnerArtifact:
        client = self._client_for(access_context)
        self._active[task_id] = client
        try:
            return await client.download(
                task_id,
                url,
                plan,
                expected_provider_media_id=expected_provider_media_id,
                expected_extractor_key=expected_extractor_key,
                access_context=access_context,
                media_kind=media_kind,
                asset_count=asset_count,
            )
        finally:
            self._active.pop(task_id, None)

    async def status(self, task_id: str) -> RunnerProgress:
        return await self._active.get(task_id, self._session).status(task_id)

    async def cancel(self, task_id: str) -> None:
        await self._active.get(task_id, self._session).cancel(task_id)

    async def close(self) -> None:
        await self._session.close()

    def _client_for(self, context: ProviderAccessContextRef) -> MediaRunnerClient:
        client = self._client_for_mode(context.provider_key, context.access_mode)
        if client is not None:
            return client
        raise MediaRunnerClientError("credential_required", 422)

    def _client_for_mode(
        self, provider_key: str, access_mode: ProviderAccessMode
    ) -> MediaRunnerClient | None:
        return (
            self._session
            if access_mode
            in {
                provider_profile_for_key(provider_key).initial_access_mode,
                provider_profile_for_key(provider_key).execution_access_mode,
            }
            else None
        )


def _error_code(response: httpx.Response) -> str:
    try:
        value = response.json()["error"]["code"]
    except (KeyError, TypeError, ValueError):
        return "runner_failed"
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value)
        else "runner_failed"
    )


def _request_phase(target: str) -> FailurePhase:
    if target == "/internal/inspect":
        return FailurePhase.FETCH_METADATA
    if target == "/internal/download":
        return FailurePhase.TRANSFER
    return FailurePhase.PREPARE_CONTEXT


def _response_failure(
    response: httpx.Response, *, phase: FailurePhase
) -> ProviderFailure:
    try:
        document = response.json().get("error")
    except (AttributeError, ValueError):
        document = None
    if isinstance(document, dict) and "failure" in document:
        try:
            failure = RunnerErrorContract.model_validate(document).failure.to_domain()
        except (ValueError, ValidationError) as exc:
            raise MediaRunnerClientError("invalid_runner_response", 502) from exc
    else:
        # Authentication/protocol failures may not carry execution facts. Their
        # evidence remains unknown; do not manufacture a platform observation.
        failure = ProviderFailure.for_code(_error_code(response), phase=phase)
    retry_after = _retry_after(response.headers.get("Retry-After"))
    return (
        failure
        if failure.retry_after is not None or retry_after is None
        else replace(
            failure,
            retry_after=retry_after,
        )
    )


def _inspection_error(
    error: MediaRunnerClientError, *, before_media_io: bool
) -> MediaInspectionFailure:
    code = error.code
    if code in ContentRestriction:
        failure: MediaInspectionFailure = MediaInspectionPaidContentRestricted(
            ContentRestriction(code)
        )
    elif code == "provider_rate_limited":
        failure = MediaInspectionRateLimited(retry_at=error.retry_at)
    elif code in {"provider_session_not_ready", "provider_session_unavailable"}:
        failure = MediaInspectionSessionNotReady(before_media_io=before_media_io)
    else:
        error_type = {
            "duration_limit_exceeded": MediaInspectionDurationLimitExceeded,
            "credential_required": MediaInspectionAuthRequired,
            "provider_session_not_allowed": MediaInspectionPolicyNotAllowed,
            "credential_expired": MediaInspectionSessionExpired,
            "credential_rejected": MediaInspectionSessionExpired,
            "egress_challenged": MediaInspectionVerificationFailed,
            "provider_geo_restricted": MediaInspectionGeoRestricted,
            "content_private": MediaInspectionContentRestricted,
            "content_not_entitled": MediaInspectionContentRestricted,
            "content_entitlement_unknown": MediaInspectionContentRestricted,
            "credential_entitlement_drift": MediaInspectionContentRestricted,
            "drm_protected": MediaInspectionDrmProtected,
            "provider_link_unavailable": MediaInspectionLinkUnavailable,
            "content_deleted": MediaInspectionLinkUnavailable,
            "provider_media_unsupported": MediaInspectionMediaUnsupported,
            "unsupported_source": MediaInspectionMediaUnsupported,
            "format_unavailable": MediaInspectionFormatUnavailable,
            "provider_unsupported": MediaInspectionUnsupported,
            "inspection_timeout": MediaInspectionTimeout,
            "pot_provider_unavailable": MediaInspectionTemporarilyUnavailable,
            "pot_provider_release_mismatch": MediaInspectionTemporarilyUnavailable,
            "extractor_regression": MediaInspectionTemporarilyUnavailable,
            "provider_temporarily_unavailable": MediaInspectionTemporarilyUnavailable,
            "runner_unavailable": MediaInspectionTemporarilyUnavailable,
            "runner_release_mismatch": MediaInspectionTemporarilyUnavailable,
            "runner_release_changed": MediaInspectionTemporarilyUnavailable,
            "runner_restarted": MediaInspectionTemporarilyUnavailable,
            "browser_unavailable": MediaInspectionTemporarilyUnavailable,
            "browser_release_changed": MediaInspectionTemporarilyUnavailable,
            "browser_capacity_exhausted": MediaInspectionTemporarilyUnavailable,
            "browser_profile_limit": MediaInspectionTemporarilyUnavailable,
            "credential_access_denied": MediaInspectionTemporarilyUnavailable,
            "source_read_timeout": MediaInspectionTemporarilyUnavailable,
            "source_read_failed": MediaInspectionTemporarilyUnavailable,
            "chrome_profile_unavailable": MediaInspectionTemporarilyUnavailable,
        }.get(code, MediaInspectionFailure)
        failure = error_type(code)
    return failure.with_failure(error.failure)


def _retry_after(value: str | None) -> datetime | None:
    return parse_retry_after(value, datetime.now(UTC))


def _context_to_domain(
    contract: ProviderAccessContextContract,
) -> ProviderAccessContextRef:
    try:
        context = contract.to_domain()
    except ValueError as exc:
        raise MediaRunnerClientError("invalid_runner_response", 502) from exc
    if context.runtime_revision == "legacy":
        raise MediaRunnerClientError("runner_release_mismatch", 503)
    return context
