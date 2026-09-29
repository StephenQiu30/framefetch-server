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
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
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
from app.services.downloads.rules.content_restrictions import ContentRestriction
from app.services.downloads.rules.enums import MediaKind
from app.services.downloads.rules.formats import DownloadPlan
from app.services.provider_access import ProviderAccessPolicy
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
    InspectRequest,
    InspectResponse,
    ProviderAccessContextContract,
    ProviderContextRequest,
    ProviderContextsRequest,
    ProviderContextsResponse,
    ProviderLoginRequest,
    ProviderLoginResponse,
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
    async def login(self, url: str, *, finish: bool = False) -> None: ...

    """Runner strategy used by the routing facade."""

    async def engine_catalog(self) -> EngineCatalogResponse: ...

    async def context(self, url: str) -> ProviderAccessContextRef: ...

    async def contexts_for_providers(
        self, provider_keys: tuple[str, ...]
    ) -> tuple[ProviderAccessContextRef, ...]: ...

    async def inspect(self, url: str) -> RunnerInspection: ...

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
        return await self._request(
            "GET",
            "/internal/engine-catalog",
            b"",
            EngineCatalogResponse,
            15.0,
            timeout_code="engine_catalog_unavailable",
        )

    async def context(self, url: str) -> ProviderAccessContextRef:
        provider_key = provider_profile(url).key
        response = await self._request(
            "POST",
            "/internal/context",
            ProviderContextRequest(url=url).model_dump_json().encode(),
            ProviderAccessContextContract,
            min(self._inspect_timeout, _CONTEXT_TIMEOUT_SECONDS),
            timeout_code="inspection_timeout",
        )
        context = _context_to_domain(response)
        expected_mode = (
            provider_profile_for_key(provider_key).execution_access_mode
            if self._expected_access_mode is ProviderAccessMode.OPERATOR_MANAGED
            else self._expected_access_mode
        )
        if context.provider_key != provider_key or (
            expected_mode is not None and context.access_mode is not expected_mode
        ):
            raise MediaRunnerClientError("client_context_mismatch", 502)
        return context

    async def contexts_for_providers(
        self, provider_keys: tuple[str, ...]
    ) -> tuple[ProviderAccessContextRef, ...]:
        response = await self._request(
            "POST",
            "/internal/contexts",
            ProviderContextsRequest(provider_keys=list(provider_keys))
            .model_dump_json()
            .encode(),
            ProviderContextsResponse,
            min(self._inspect_timeout, _STATUS_CONTEXT_TIMEOUT_SECONDS),
            timeout_code="inspection_timeout",
        )
        return tuple(_context_to_domain(context) for context in response.contexts)

    async def inspect(self, url: str) -> RunnerInspection:
        context_ready = False
        context = None
        try:
            context = (
                await self.context(url)
                if self._admission is not None or self._expected_access_mode is not None
                else None
            )
            context_ready = context is not None
            if self._admission is None:
                response = await self._inspect_response(url, context)
            else:
                assert context is not None
                response = await self._admission.run(
                    context,
                    lambda deadline: self._inspect_response(url, context, deadline),
                )
        except RouteCoolingDown as exc:
            raise MediaInspectionRateLimited(retry_at=exc.retry_at) from exc
        except RouteProbeTimeout as exc:
            raise MediaInspectionTimeout from exc
        except RouteAdmissionUnavailable as exc:
            raise MediaInspectionTemporarilyUnavailable from exc
        except MediaRunnerClientError as exc:
            if exc.code in ContentRestriction:
                raise MediaInspectionPaidContentRestricted(
                    ContentRestriction(exc.code)
                ) from exc
            if exc.code == "duration_limit_exceeded":
                raise MediaInspectionDurationLimitExceeded from exc
            if exc.code == "credential_required":
                raise MediaInspectionAuthRequired from exc
            if exc.code == "provider_session_not_allowed":
                raise MediaInspectionPolicyNotAllowed from exc
            if exc.code in {
                "provider_session_not_ready",
                "provider_session_unavailable",
            }:
                raise MediaInspectionSessionNotReady(
                    before_media_io=not context_ready
                ) from exc
            if exc.code in {
                "credential_expired",
                "credential_rejected",
                "credential_revoked",
                "credential_entitlement_drift",
            }:
                raise MediaInspectionSessionExpired from exc
            if exc.code in {
                "egress_challenged",
                "pot_required",
                "pot_rejected",
                "client_context_mismatch",
            }:
                raise MediaInspectionVerificationFailed from exc
            if exc.code == "provider_rate_limited":
                raise MediaInspectionRateLimited from exc
            if exc.code == "provider_geo_restricted":
                raise MediaInspectionGeoRestricted from exc
            if exc.code in {
                "content_private",
                "content_not_entitled",
                "content_entitlement_unknown",
            }:
                raise MediaInspectionContentRestricted from exc
            if exc.code == "drm_protected":
                raise MediaInspectionDrmProtected from exc
            if exc.code in {
                "pot_provider_unavailable",
                "pot_provider_release_mismatch",
                "extractor_regression",
                "provider_temporarily_unavailable",
                "provider_session_unavailable",
                "runner_unavailable",
                "runner_release_mismatch",
                "runner_release_changed",
            }:
                raise MediaInspectionTemporarilyUnavailable from exc
            if exc.code == "provider_link_unavailable":
                raise MediaInspectionLinkUnavailable from exc
            if exc.code == "provider_media_unsupported":
                raise MediaInspectionMediaUnsupported from exc
            if exc.code == "unsupported_source":
                # Preserve the selected route's diagnosis; never retry it
                # with a different account or access policy.
                raise MediaInspectionMediaUnsupported from exc
            if exc.code == "format_unavailable":
                raise MediaInspectionFormatUnavailable from exc
            if exc.code == "provider_unsupported":
                raise MediaInspectionUnsupported from exc
            if exc.code == "inspection_timeout":
                raise MediaInspectionTimeout from exc
            raise MediaInspectionFailure(exc.code) from exc
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

    async def _inspect_response(
        self,
        url: str,
        context: ProviderAccessContextRef | None = None,
        deadline_at: datetime | None = None,
    ) -> InspectResponse:
        response = await self._request(
            "POST",
            "/internal/inspect",
            InspectRequest(
                url=url,
                access_context=(
                    None
                    if context is None
                    else ProviderAccessContextContract.from_domain(context)
                ),
                deadline_at=deadline_at,
            )
            .model_dump_json()
            .encode(),
            InspectResponse,
            self._inspect_timeout,
            timeout_code="inspection_timeout",
        )
        if context is not None:
            returned_context = _context_to_domain(response.access_context)
            if returned_context.runtime_revision == "legacy":
                # A rollback Runner emits its own legacy identity. Its inspect
                # result still has to match every other frozen route reference.
                returned_context = replace(
                    returned_context, runtime_revision=context.runtime_revision
                )
            if returned_context != context:
                raise MediaRunnerClientError("client_context_mismatch", 422)
            if not response.options:
                raise MediaRunnerClientError("format_unavailable", 422)
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

        response = (
            await execute()
            if self._admission is None
            else await self._admission.run(
                access_context,
                execute,
                owner=task_id,
                probe=lambda deadline: self._inspect_response(
                    url, access_context, deadline
                ),
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

    async def login(self, url: str, *, finish: bool = False) -> None:
        await self._request(
            "POST",
            "/internal/site-sessions/login",
            ProviderLoginRequest(url=url, finish=finish).model_dump_json().encode(),
            ProviderLoginResponse,
            40,
            timeout_code="provider_session_not_ready",
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
    ) -> ResponseModel:
        timestamp, nonce = self._clock(), self._nonce()
        headers = {
            "Content-Type": "application/json",
            "X-Runner-Timestamp": str(timestamp),
            "X-Runner-Nonce": nonce,
            "X-Runner-Signature": sign_request(
                self._secret, method, target, body, timestamp, nonce
            ),
        }
        try:
            response = await self._client.request(
                method,
                target,
                content=body,
                headers=headers,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise MediaRunnerClientError(timeout_code, 504) from exc
        except httpx.HTTPError as exc:
            raise MediaRunnerClientError("runner_unavailable", 503) from exc
        if response.is_error:
            raise MediaRunnerClientError(
                _error_code(response),
                response.status_code,
                retry_at=_retry_after(response.headers.get("Retry-After")),
            )
        try:
            return model.model_validate_json(response.content)
        except ValidationError as exc:
            raise MediaRunnerClientError("invalid_runner_response", 502) from exc

    @staticmethod
    def _validate_task_id(task_id: str) -> None:
        if _TASK_ID.fullmatch(task_id) is None:
            raise ValueError("invalid runner task id")


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

    async def login(self, url: str, *, finish: bool = False) -> None:
        await self._session.login(url, finish=finish)

    async def resolve_access_policy(
        self, url: str, requested: ProviderAccessPolicy | None = None
    ) -> ProviderAccessPolicy:
        return await self._inspection_pipeline.resolve_access_policy(url, requested)

    async def engine_catalog(self) -> EngineCatalogResponse:
        return await self._session.engine_catalog()

    async def inspect(
        self, url: str, *, access_policy: ProviderAccessPolicy | None = None
    ) -> RunnerInspection:
        return await self._inspection_pipeline.inspect(url, access_policy=access_policy)

    async def context(
        self, url: str, access_mode: ProviderAccessMode
    ) -> ProviderAccessContextRef:
        client = self._client_for_mode(provider_profile(url).key, access_mode)
        if client is None:
            raise MediaRunnerClientError("credential_required", 422)
        context = await client.context(url)
        if context.access_mode is not access_mode:
            raise MediaRunnerClientError("client_context_mismatch", 502)
        return context

    async def contexts_for_providers(
        self,
        requested: Mapping[str, ProviderAccessMode],
    ) -> Mapping[str, ProviderAccessContextRef]:
        groups = [
            (self._session, (key,))
            for key, mode in requested.items()
            if mode is provider_profile_for_key(key).execution_access_mode
        ]

        async def resolve(
            client: MediaRunnerClient,
            keys: tuple[str, ...],
        ) -> tuple[ProviderAccessContextRef, ...]:
            try:
                return await client.contexts_for_providers(keys)
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
            *(resolve(client, keys) for client, keys in groups)
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
            is provider_profile_for_key(provider_key).execution_access_mode
            else None
        )


def _error_code(response: httpx.Response) -> str:
    try:
        value = response.json()["error"]["code"]
    except (KeyError, TypeError, ValueError):
        return "runner_failed"
    return value if isinstance(value, str) and value else "runner_failed"


def _retry_after(value: str | None) -> datetime | None:
    if value is None or len(value) > 128:
        return None
    now = datetime.now(UTC)
    try:
        if value.isascii() and value.isdigit():
            return now + timedelta(seconds=int(value))
        result = parsedate_to_datetime(value)
        return result if result.tzinfo is not None and result > now else None
    except (ValueError, TypeError, OverflowError):
        return None


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
