from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict, is_dataclass, replace
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal
from uuid import uuid4

from app.services.downloads.rules.enums import Container, MediaKind, StreamKind
from app.services.downloads.rules.errors import FormatSelectionError
from app.services.downloads.rules.formats import CandidateStream, ProviderHints
from app.services.downloads.rules.selection import select_streams
from app.services.provider_failures import FailurePhase
from app.services.provider_types import ExecutionContext, ProviderIdentity
from app.workers.runner.active_tasks import ActiveTaskRegistry
from app.workers.runner.browser_runtime import BrowserRuntime
from app.workers.runner.collection import download_video_collection_zip
from app.workers.runner.command_support import default_supervisor
from app.workers.runner.commands import MediaCommands, ProcessRunner
from app.workers.runner.contracts import (
    ArtifactContract,
    CancelResponse,
    DownloadRequest,
    DownloadResponse,
    InspectResponse,
    RunnerTaskStage,
    SelectedStreamsContract,
    TaskStatusResponse,
)
from app.workers.runner.engine.egress import resolve_egress
from app.workers.runner.engine.ladder import run_ladder
from app.workers.runner.engine.run_context import ResolutionSource, RunContext
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.gallery import download_gallery_zip
from app.workers.runner.inspection_pipeline import RunnerInspectionPipeline
from app.workers.runner.metadata import (
    MediaInspection,
    build_download_options,
    collection_fallback_assets,
)
from app.workers.runner.presentation import inspect_response
from app.workers.runner.provider_errors import ProviderFailureContext
from app.workers.runner.provider_registry import (
    ProviderRequest,
    provider_request,
)
from app.workers.runner.resolved_info import write_resolved_info
from app.workers.runner.settings import RunnerSettings
from app.workers.runner.thumbnails import ThumbnailFetcher
from app.workers.runner.utilities import (
    file_sha256,
    require_source_identity,
    safe_media_url,
)
from app.workers.runner.verification import verify_probe
from app.workers.runner.workspace import (
    TaskWorkspace,
    WorkspaceLimits,
    WorkspaceManager,
    WorkspaceViolation,
)


class MediaRunnerService:
    def __init__(
        self,
        settings: RunnerSettings,
        *,
        supervisor: ProcessRunner | None = None,
    ) -> None:
        self._settings = settings
        self._browser = BrowserRuntime(settings)
        self._commands = MediaCommands(
            settings,
            supervisor or default_supervisor(settings),
        )
        self._inspection = RunnerInspectionPipeline(settings, self._commands)
        self._thumbnails = ThumbnailFetcher(settings)
        self._workspaces = WorkspaceManager(
            settings.runner_workspace_root,
            WorkspaceLimits(
                max_output_files=settings.runner_max_output_files,
                max_output_bytes=settings.runner_max_output_bytes,
                max_workspace_bytes=settings.runner_max_workspace_bytes,
            ),
        )
        self._active = ActiveTaskRegistry(settings.runner_max_active_tasks)
        self._engine_revision = _engine_revision(settings)

    async def close(self) -> None:
        await self._browser.close()

    def _context(self, source: ProviderRequest) -> ExecutionContext:
        egress = resolve_egress(source.profile, settings=self._settings)
        return ExecutionContext(
            provider_key=source.profile.key,
            resolved_layer="L1",
            egress_route=egress.route,
            registry_revision=_registry_revision(source),
            client=source.profile.client_profile,
            egress_revision=egress.revision,
            egress_class=egress.egress_class,
            egress_observed_ip=egress.observed_ip,
            identity_digest=None,
            browser_context_kind="none",
            identity_used=False,
            engine_revision=self._engine_revision,
        )

    def _validate_context(
        self, source: ProviderRequest, expected: ExecutionContext | None
    ) -> ExecutionContext:
        context = self._context(source)
        if expected is not None and expected != context:
            raise RunnerFailure("context_changed", status=409, gate="③")
        if source.profile.identity is ProviderIdentity.REQUIRED:
            raise RunnerFailure("login_required", status=422).attributed_to(context)
        return context

    async def inspect(
        self,
        url: str,
        *,
        execution_context: ExecutionContext | None = None,
        task_id: str | None = None,
        deadline: datetime | None = None,
    ) -> InspectResponse:
        task = asyncio.current_task()
        if task is None:
            raise RunnerFailure("runtime_unavailable", status=500)
        if task.cancelling():
            raise asyncio.CancelledError
        deadline = deadline or datetime.now(UTC) + timedelta(
            seconds=min(120, self._settings.runner_inspect_timeout_seconds)
        )
        remaining = min(
            120,
            self._settings.runner_inspect_timeout_seconds,
            (deadline - datetime.now(UTC)).total_seconds(),
        )
        if remaining <= 0:
            raise RunnerFailure("inspection_timeout", status=504)
        resource_id = task_id or f"parse_{uuid4().hex}"
        source = provider_request(safe_media_url(url))
        context = self._validate_context(source, execution_context)
        self._active.register(resource_id, task)
        workspace = None
        try:
            workspace = self._workspaces.create(resource_id)
            async with asyncio.timeout(remaining):
                inspection = await self._resolve_with_retries(
                    source,
                    workspace,
                    context=context,
                    cookie_jar=None,
                    deadline=deadline,
                )
                plans = (
                    build_download_options(
                        inspection.streams,
                        max_options=self._settings.runner_max_options,
                    )
                    if inspection.media_kind is MediaKind.VIDEO
                    else ()
                )
                if inspection.media_kind is MediaKind.VIDEO and not plans:
                    raise RunnerFailure("format_unavailable", status=409)
                thumbnail_data_url = await self._thumbnails.fetch(
                    inspection.thumbnail_urls,
                    referer=source.source_url,
                    egress_proxy=self._settings.egress_proxy_for(context.provider_key),
                )
                return inspect_response(
                    inspection,
                    plans,
                    execution_context=context,
                    thumbnail_data_url=thumbnail_data_url,
                )
        except TimeoutError as exc:
            raise RunnerFailure("transient", status=504).attributed_to(context) from exc
        except RunnerFailure as error:
            error.attributed_to(context)
            raise
        finally:
            if workspace is not None:
                workspace.cleanup()
            self._active.discard(resource_id, task)

    async def download(self, request: DownloadRequest) -> DownloadResponse:
        task = asyncio.current_task()
        if task is None:
            raise RunnerFailure("internal_error", status=500)
        if task.cancelling():
            raise asyncio.CancelledError
        remaining = self._settings.runner_download_timeout_seconds
        if request.deadline is not None:
            remaining = min(
                remaining, (request.deadline - datetime.now(UTC)).total_seconds()
            )
        if remaining <= 0:
            raise RunnerFailure("download_timeout", status=504, stage="download")
        self._active.register(request.task_id, task)
        workspace = None
        context = None
        phase = FailurePhase.PREPARE_CONTEXT

        def current_phase() -> FailurePhase:
            snapshot = self._active.status(request.task_id)
            if snapshot is None:
                return phase
            return {
                RunnerTaskStage.DOWNLOADING: FailurePhase.TRANSFER,
                RunnerTaskStage.REMUXING: FailurePhase.VALIDATE,
                RunnerTaskStage.VERIFYING: FailurePhase.VALIDATE,
            }.get(snapshot.stage, phase)

        def current_stage() -> Literal["download", "validate"]:
            return (
                "validate"
                if current_phase() in {FailurePhase.PROBE_MEDIA, FailurePhase.VALIDATE}
                else "download"
            )

        succeeded = False
        try:
            async with asyncio.timeout(remaining):
                safe_url = safe_media_url(request.url)
                source = provider_request(safe_url)
                context = self._validate_context(
                    source, request.execution_context.to_domain()
                )
                workspace = self._workspaces.create(request.task_id)
                phase = FailurePhase.FETCH_METADATA
                response = await self._download_in_workspace(
                    request, source, workspace, context=context, cookie_jar=None
                )
            self._active.complete(request.task_id, task)
            succeeded = True
            return response
        except asyncio.CancelledError as exc:
            raise RunnerFailure(
                "cancelled", status=409, phase=current_phase(), stage=current_stage()
            ).attributed_to(context) from exc
        except TimeoutError as exc:
            raise RunnerFailure(
                "download_timeout",
                status=504,
                phase=current_phase(),
                stage=current_stage(),
            ).attributed_to(context) from exc
        except WorkspaceViolation as exc:
            raise RunnerFailure(
                "workspace_limit_exceeded",
                status=413,
                phase=current_phase(),
                stage=current_stage(),
            ).attributed_to(context) from exc
        except RunnerFailure as error:
            if context is not None:
                error.attributed_to(context)
            if error.failure.stage != "validate":
                error.failure = replace(error.failure, stage="download")
            raise
        finally:
            self._active.discard(request.task_id, task)
            if workspace is not None and not succeeded:
                workspace.cleanup()

    async def cancel(self, task_id: str) -> CancelResponse:
        await self._active.cancel(task_id)
        return CancelResponse(task_id=task_id)

    async def status(self, task_id: str) -> TaskStatusResponse:
        snapshot = self._active.status(task_id)
        if snapshot is None:
            raise RunnerFailure("task_not_found", status=404)
        return TaskStatusResponse(
            task_id=task_id,
            stage=snapshot.stage,
            progress=snapshot.progress,
        )

    async def _resolve_with_retries(
        self,
        source: ProviderRequest,
        workspace: TaskWorkspace,
        *,
        context: ExecutionContext,
        cookie_jar: Path | None,
        deadline: datetime,
    ) -> MediaInspection:
        resolution = await run_ladder(
            ResolutionSource(
                request=source,
                workspace=workspace,
                pipeline=self._inspection,
                execution_context=context,
                run_context=RunContext(
                    egress=resolve_egress(source.profile, settings=self._settings),
                    user_agent="",  # Preserve yt-dlp's R0 default user agent.
                    referer=source.source_url,
                    cookie_file=cookie_jar,
                    identity=None,
                    browser=None,
                    deadline=deadline,
                ),
            ),
            source.profile,
            deadline,
        )
        if resolution.execution_context != context:
            raise RunnerFailure("context_changed", status=409).attributed_to(context)
        return resolution.media

    async def _download_in_workspace(
        self,
        request: DownloadRequest,
        source: ProviderRequest,
        workspace: TaskWorkspace,
        *,
        context: ExecutionContext,
        cookie_jar: Path | None,
    ) -> DownloadResponse:
        inspection = await self._resolve_with_retries(
            source,
            workspace,
            context=context,
            cookie_jar=cookie_jar,
            deadline=request.deadline
            or datetime.now(UTC)
            + timedelta(seconds=self._settings.runner_download_timeout_seconds),
        )
        failure_context = ProviderFailureContext(
            provider_key=source.profile.key,
            source_url=source.source_url,
            authenticated=context.identity_used,
        )
        require_source_identity(
            inspection,
            provider_media_id=request.expected_provider_media_id,
            extractor_key=request.expected_extractor_key,
        )
        if inspection.media_kind in {
            MediaKind.IMAGE_GALLERY,
            MediaKind.VIDEO_COLLECTION,
        }:
            if (
                request.media_kind is not inspection.media_kind
                or request.asset_count != inspection.asset_count
            ):
                raise RunnerFailure("source_changed", status=409)
            if request.media_kind is MediaKind.VIDEO_COLLECTION:
                self._active.update(request.task_id, RunnerTaskStage.DOWNLOADING, 10)
                count = await download_video_collection_zip(
                    source,
                    workspace.path / "artifact.zip",
                    workspace,
                    expected_count=request.asset_count,
                    title=inspection.title,
                    referer=source.source_url,
                    commands=self._commands,
                    max_video_bytes=self._settings.runner_max_output_bytes,
                    max_duration_seconds=self._settings.runner_max_duration_seconds,
                    max_assets=self._settings.runner_max_gallery_assets,
                    cookie_jar=cookie_jar,
                    fallback_assets=collection_fallback_assets(
                        inspection.download_info
                    ),
                )
            else:
                self._active.update(request.task_id, RunnerTaskStage.DOWNLOADING, 10)
                count = await download_gallery_zip(
                    inspection.gallery_assets,
                    workspace.path / "artifact.zip",
                    workspace,
                    title=inspection.title,
                    referer=source.source_url,
                    commands=self._commands,
                    max_asset_bytes=self._settings.runner_max_gallery_asset_bytes,
                    max_assets=self._settings.runner_max_gallery_assets,
                )
            artifact = workspace.path / "artifact.zip"
            workspace.validate_usage()
            output = workspace.validate_outputs([artifact.name])[0]
            self._active.update(request.task_id, RunnerTaskStage.VERIFYING, 90)
            digest = await asyncio.to_thread(file_sha256, artifact)
            return DownloadResponse(
                task_id=request.task_id,
                workspace_path=str(workspace.path),
                artifact=ArtifactContract(
                    relative_path=artifact.name,
                    size_bytes=output.size,
                    sha256=digest,
                    duration_seconds=0,
                    container=Container.ZIP,
                    video_streams=0,
                    audio_streams=0,
                    media_kind=request.media_kind,
                    asset_count=count,
                ),
                selection=None,
            )
        if request.plan is None or request.media_kind.value != "video":
            raise RunnerFailure("source_changed", status=409)
        plan = request.plan.to_domain()
        try:
            # Provider format ids are only short-lived hints. Re-inspection is
            # the source of truth because YouTube can reject one rendition
            # while another stream with the same semantic plan remains valid.
            selection = select_streams(
                replace(plan, hints=ProviderHints()), inspection.streams
            )
        except FormatSelectionError as exc:
            raise RunnerFailure(exc.code.value, status=409) from exc

        info_json = workspace.path / "resolved.info.json"
        await asyncio.to_thread(
            write_resolved_info,
            info_json,
            inspection.download_info,
        )

        inputs = [workspace.path / "video.input"]
        total_streams = 1 if selection.audio is None else 2
        self._active.update(request.task_id, RunnerTaskStage.DOWNLOADING, 10)
        await self._download_stream_with_progress(
            request.task_id,
            source,
            selection.video,
            inputs[0],
            workspace,
            start_progress=10,
            end_progress=10 + 60 // total_streams,
            duration_seconds=inspection.duration_seconds,
            cookie_jar=cookie_jar,
            info_json=info_json,
        )
        completed_streams = 1
        progress = 10 + 60 * completed_streams // total_streams
        self._active.update(request.task_id, RunnerTaskStage.DOWNLOADING, progress)
        if selection.audio is not None:
            inputs.append(workspace.path / "audio.input")
            await self._download_stream_with_progress(
                request.task_id,
                source,
                selection.audio,
                inputs[1],
                workspace,
                start_progress=progress,
                end_progress=70,
                duration_seconds=inspection.duration_seconds,
                cookie_jar=cookie_jar,
                info_json=info_json,
            )
            completed_streams += 1
            progress = 10 + 60 * completed_streams // total_streams
            self._active.update(request.task_id, RunnerTaskStage.DOWNLOADING, progress)
        workspace.validate_usage()

        artifact = workspace.path / f"artifact.{selection.output_container.value}"
        self._active.update(request.task_id, RunnerTaskStage.REMUXING, 75)
        await self._commands.remux(
            tuple(inputs),
            artifact,
            selection.output_container,
            workspace.path,
            include_audio=(
                selection.audio is not None or selection.video.kind is StreamKind.MUXED
            ),
            failure_context=failure_context,
        )
        try:
            output = workspace.validate_outputs([artifact.name])[0]
        except WorkspaceViolation as exc:
            raise RunnerFailure(
                "invalid_artifact", status=502, phase=FailurePhase.VALIDATE
            ) from exc
        self._active.update(request.task_id, RunnerTaskStage.VERIFYING, 85)
        probe_payload = await self._commands.probe(
            artifact,
            workspace.path,
            failure_context=failure_context,
            phase=FailurePhase.VALIDATE,
        )
        verification_plan = plan
        if selection.video.width is not None and selection.video.height is not None:
            verification_plan = replace(
                plan,
                width=selection.video.width,
                height=selection.video.height,
            )
        verified = verify_probe(
            probe_payload,
            plan=verification_plan,
            expected_container=selection.output_container,
            expected_duration=inspection.duration_seconds,
            max_duration=self._settings.runner_max_duration_seconds,
            tolerance_seconds=self._settings.runner_duration_tolerance_seconds,
        )
        digest = await asyncio.to_thread(file_sha256, artifact)
        return DownloadResponse(
            task_id=request.task_id,
            workspace_path=str(workspace.path),
            artifact=ArtifactContract(
                relative_path=artifact.name,
                size_bytes=output.size,
                sha256=digest,
                duration_seconds=verified.duration_seconds,
                container=selection.output_container,
                video_streams=verified.video_streams,
                audio_streams=verified.audio_streams,
            ),
            selection=SelectedStreamsContract(
                video_provider_id=selection.video.provider_id,
                audio_provider_id=(
                    selection.audio.provider_id if selection.audio is not None else None
                ),
                output_container=selection.output_container,
            ),
        )

    async def _download_stream_with_progress(
        self,
        task_id: str,
        source: ProviderRequest,
        stream: CandidateStream,
        output: Path,
        workspace: TaskWorkspace,
        *,
        start_progress: int,
        end_progress: int,
        duration_seconds: float,
        cookie_jar: Path | None,
        info_json: Path,
    ) -> None:
        operation = asyncio.create_task(
            self._commands.download_stream(
                source,
                stream.provider_id,
                output,
                workspace.path,
                cookie_jar=cookie_jar,
                info_json=info_json,
            )
        )
        expected_bytes = _estimated_stream_bytes(stream, duration_seconds)
        last_progress = start_progress
        try:
            while not operation.done():
                done, _ = await asyncio.wait(
                    {operation},
                    timeout=self._settings.runner_workspace_poll_interval_seconds,
                )
                if operation in done:
                    break
                observed_bytes = await asyncio.to_thread(
                    _partial_download_bytes,
                    output,
                )
                current = _stream_progress(
                    observed_bytes,
                    expected_bytes,
                    start=start_progress,
                    end=end_progress,
                )
                if current > last_progress:
                    self._active.update(
                        task_id,
                        RunnerTaskStage.DOWNLOADING,
                        current,
                    )
                    last_progress = current
            await operation
        except BaseException:
            if not operation.done():
                operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            raise


def _estimated_stream_bytes(
    stream: CandidateStream,
    duration_seconds: float,
) -> int | None:
    if stream.size_bytes is not None:
        return stream.size_bytes
    if stream.bitrate_kbps is None or duration_seconds <= 0:
        return None
    return max(1, int(stream.bitrate_kbps * 1_000 * duration_seconds / 8))


def _partial_download_bytes(output: Path) -> int:
    largest = 0
    try:
        candidates = output.parent.glob(f"{output.name}*")
        for candidate in candidates:
            if candidate.is_file() and not candidate.is_symlink():
                largest = max(largest, candidate.stat().st_size)
    except OSError:
        return largest
    return largest


def _stream_progress(
    observed_bytes: int,
    expected_bytes: int | None,
    *,
    start: int,
    end: int,
) -> int:
    if observed_bytes <= 0 or expected_bytes is None or expected_bytes <= 0:
        return start
    completed = min(observed_bytes / expected_bytes, 0.99)
    return min(end - 1, start + int((end - start) * completed))


def _registry_revision(source: ProviderRequest) -> str:
    profile = source.profile
    facts = {
        name: sorted(value)
        if isinstance(value, frozenset)
        else f"{value.__module__}:{value.__qualname__}"
        if callable(value)
        else asdict(value)
        if is_dataclass(value) and not isinstance(value, type)
        else value
        for name in profile.__dataclass_fields__
        if name != "display_name"
        for value in (getattr(profile, name),)
    }
    return hashlib.sha256(
        json.dumps(facts, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _engine_revision(settings: RunnerSettings) -> str:
    facts = {}
    for package in (
        "yt-dlp",
        "bgutil-ytdlp-pot-provider",
        "yt-dlp-ejs",
        "yt-dlp-getpot-wpc",
        "playwright",
    ):
        try:
            facts[package] = version(package)
        except PackageNotFoundError:
            facts[package] = "absent"
    facts["yt-dlp-commit"] = settings.runner_ytdlp_commit
    facts["javascript-runtime"] = settings.runner_ytdlp_js_runtime
    facts["bgutil-service"] = settings.runner_youtube_pot_provider_version
    digest = hashlib.sha256(json.dumps(facts, sort_keys=True).encode())
    root = Path(__file__).resolve().parent
    for path in sorted((root / "plugins").rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()
