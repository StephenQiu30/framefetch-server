"""HMAC-authenticated client for the isolated Media Runner."""

from __future__ import annotations

import asyncio
import json
import math
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

import httpx
from pydantic import BaseModel, ValidationError

from app.integrations.media_runner_models import (
    MediaRunnerClientError,
    RunnerArtifact,
    RunnerProgress,
    download_stage,
)
from app.schemas.engine_catalog import EngineCatalogResponse
from app.services.downloads.errors import MediaInspectionFailure
from app.services.downloads.inspection_models import RunnerFormat, RunnerInspection
from app.services.downloads.rules.enums import MediaKind
from app.services.downloads.rules.formats import DownloadPlan
from app.services.provider_failures import (
    FailureEvidenceKind,
    FailurePhase,
    ProviderFailure,
    parse_retry_after,
)
from app.services.provider_types import ExecutionContext
from app.workers.runner.contracts import (
    CancelCommand,
    CancelResponse,
    DownloadPlanContract,
    DownloadRequest,
    DownloadResponse,
    ExecutionContextContract,
    InspectRequest,
    InspectResponse,
    RunnerErrorContract,
    RuntimeResponse,
    TaskStatusResponse,
)
from app.workers.runner.signing import sign_request

_TASK_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


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
        self._cleanup_tokens: dict[str, tuple[str, float]] = {}
        self._client = client or httpx.AsyncClient(base_url=base_url)

    async def engine_catalog(self) -> EngineCatalogResponse:
        return await self._request(
            "GET",
            "/internal/engine-catalog",
            b"",
            EngineCatalogResponse,
            15.0,
            timeout_code="runtime_unavailable",
        )

    async def inspect(
        self, url: str, *, task_id: str | None = None, deadline: datetime | None = None
    ) -> RunnerInspection:
        try:
            return await self._inspect(url, task_id=task_id, deadline=deadline)
        except MediaRunnerClientError as exc:
            raise MediaInspectionFailure(exc.code, failure=exc.failure) from exc

    async def _inspect(
        self, url: str, *, task_id: str | None = None, deadline: datetime | None = None
    ) -> RunnerInspection:
        requested_at = datetime.now(UTC)
        deadline = deadline or requested_at + timedelta(
            seconds=min(120, self._inspect_timeout)
        )
        if deadline <= requested_at:
            raise MediaRunnerClientError("transient", 504)
        resource_id = task_id or f"parse_{uuid4().hex}"
        self._validate_task_id(resource_id)
        runtime = await self._runtime()
        try:
            response = await self._request(
                "POST",
                "/internal/inspect",
                InspectRequest(
                    url=url,
                    task_id=resource_id,
                    deadline=deadline,
                    issued_at=requested_at,
                )
                .model_dump_json()
                .encode(),
                InspectResponse,
                min(
                    self._inspect_timeout,
                    max(0, (deadline - datetime.now(UTC)).total_seconds()),
                ),
                timeout_code="transient",
                runtime_instance_id=runtime.instance_id,
            )
        except asyncio.CancelledError:
            cleanup = asyncio.create_task(
                self._cancel_resource(resource_id, runtime.instance_id)
            )
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError as exc:
                raise MediaRunnerClientError("runtime_unavailable", 503) from exc
            raise
        return _inspection_result(response)

    async def download(
        self,
        task_id: str,
        url: str,
        plan: DownloadPlan | None,
        *,
        expected_provider_media_id: str,
        expected_extractor_key: str,
        execution_context: ExecutionContext,
        media_kind: MediaKind = MediaKind.VIDEO,
        asset_count: int = 0,
    ) -> RunnerArtifact:
        self._validate_task_id(task_id)
        body = (
            DownloadRequest(
                deadline=datetime.now(UTC) + timedelta(seconds=self._download_timeout),
                task_id=task_id,
                url=url,
                expected_provider_media_id=expected_provider_media_id,
                expected_extractor_key=expected_extractor_key,
                plan=None if plan is None else DownloadPlanContract.from_domain(plan),
                execution_context=ExecutionContextContract.from_domain(
                    execution_context
                ),
                media_kind=media_kind,
                asset_count=asset_count,
            )
            .model_dump_json()
            .encode()
        )
        response = await self._request(
            "POST",
            "/internal/download",
            body,
            DownloadResponse,
            self._download_timeout,
            timeout_code="transient",
        )
        workspace = Path(response.workspace_path).resolve()
        artifact = (workspace / response.artifact.relative_path).resolve()
        if not workspace.is_relative_to(
            self._workspace_root
        ) or not artifact.is_relative_to(workspace):
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
            timeout_code="runtime_unavailable",
        )
        return RunnerProgress(download_stage(response.stage), response.progress)

    async def cancel(self, task_id: str) -> None:
        self._validate_task_id(task_id)
        runtime = await self._runtime()
        await self._cancel_resource(task_id, runtime.instance_id)

    async def _runtime(self) -> RuntimeResponse:
        return await self._request(
            "GET",
            "/internal/runtime",
            b"",
            RuntimeResponse,
            min(self._inspect_timeout, 5.0),
            timeout_code="runtime_unavailable",
        )

    async def _cancel_resource(self, task_id: str, instance_id: str) -> None:
        try:
            async with asyncio.timeout(30):
                last_error = None
                for _ in range(3):
                    try:
                        response = await self._request(
                            "POST",
                            f"/internal/tasks/{task_id}/cancel",
                            CancelCommand().model_dump_json().encode(),
                            CancelResponse,
                            min(self._inspect_timeout, 10.0),
                            timeout_code="runtime_unavailable",
                            runtime_instance_id=instance_id,
                        )
                        if (
                            response.task_id != task_id
                            or response.status != "stopped"
                            or response.cleanup_token is None
                        ):
                            raise MediaRunnerClientError("invalid_runner_response", 502)
                        observed = time.monotonic()
                        self._cleanup_tokens = {
                            key: value
                            for key, value in self._cleanup_tokens.items()
                            if observed - value[1] <= 600
                        }
                        if len(self._cleanup_tokens) >= 100_000:
                            self._cleanup_tokens.pop(next(iter(self._cleanup_tokens)))
                        self._cleanup_tokens[task_id] = (
                            response.cleanup_token,
                            observed,
                        )
                        return
                    except MediaRunnerClientError as exc:
                        last_error = exc
                        if exc.code == "runner_restarted":
                            runtime = await self._runtime()
                            if runtime.instance_id != instance_id:
                                return
                assert last_error is not None
                raise last_error
        except TimeoutError as exc:
            raise MediaRunnerClientError("runtime_unavailable", 503) from exc

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
        if timeout <= 0:
            raise MediaRunnerClientError(timeout_code, 504)
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
        if target in {"/internal/inspect", "/internal/download"}:
            document = json.loads(body)
            issued_at = datetime.fromtimestamp(timestamp, UTC).replace(
                microsecond=datetime.now(UTC).microsecond
            )
            document["issued_at"] = issued_at.isoformat()
            cleanup = self._cleanup_tokens.get(document["task_id"])
            document["cleanup_token"] = None if cleanup is None else cleanup[0]
            body = json.dumps(document, separators=(",", ":")).encode()
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
        execution_context=response.execution_context.to_domain(),
        thumbnail_data_url=response.media.thumbnail_data_url,
        media_kind=response.media.media_kind,
        asset_count=response.media.asset_count,
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
    if response.status_code == 429 and failure.failure_class.value != "rate_limited":
        failure = ProviderFailure.for_code(
            "rate_limited",
            phase=phase,
            evidence_kind=FailureEvidenceKind.UPSTREAM_RESPONSE,
            evidence={"kind": "upstream_response", "http_status": 429},
        )
    retry_after = _retry_after(response.headers.get("Retry-After"))
    return (
        failure
        if failure.retry_after is not None or retry_after is None
        else replace(
            failure,
            retry_after=retry_after,
        )
    )


def _retry_after(value: str | None) -> datetime | None:
    return parse_retry_after(value, datetime.now(UTC))
