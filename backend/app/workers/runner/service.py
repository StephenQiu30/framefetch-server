from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from app.services.downloads.rules.enums import Container, MediaKind, StreamKind
from app.services.downloads.rules.errors import FormatSelectionError
from app.services.downloads.rules.formats import CandidateStream, ProviderHints
from app.services.downloads.rules.selection import select_streams
from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_types import ProviderAccessContextRef, ProviderAccessMode
from app.workers.runner.active_tasks import ActiveTaskRegistry
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
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.gallery import download_gallery_zip
from app.workers.runner.inspection_pipeline import RunnerInspectionPipeline
from app.workers.runner.metadata import (
    build_download_options,
    collection_fallback_assets,
)
from app.workers.runner.presentation import inspect_response
from app.workers.runner.provider_errors import ProviderFailureContext
from app.workers.runner.provider_registry import (
    ProviderRequest,
    provider_profile_for_key,
    provider_request,
)
from app.workers.runner.provider_sessions import ProviderSessionStore
from app.workers.runner.release_identity import require_youtube_sidecar_identity
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

# Anonymous failures that the provider's session route is expected to clear.
_SESSION_UPGRADE_CODES = frozenset(
    {"credential_required", "egress_challenged", "provider_session_not_ready"}
)


class MediaRunnerService:
    def __init__(
        self,
        settings: RunnerSettings,
        *,
        supervisor: ProcessRunner | None = None,
        session_store: ProviderSessionStore | None = None,
    ) -> None:
        self._settings = settings
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
        self._sessions = session_store or ProviderSessionStore(settings)

    async def context(
        self, url: str, *, access_mode: ProviderAccessMode | None = None
    ) -> ProviderAccessContextRef:
        safe_url = safe_media_url(url)
        source = provider_request(safe_url)
        await self._require_companion(source.profile.key)
        return await self._sessions.context_for(
            source.profile, url=safe_url, access_mode=access_mode
        )

    async def contexts_for_providers(
        self,
        provider_keys: tuple[str, ...],
        *,
        access_mode: ProviderAccessMode | None = None,
    ) -> tuple[ProviderAccessContextRef, ...]:
        if "youtube" in provider_keys:
            await self._require_companion("youtube")
        return tuple(
            [
                await self._sessions.context_for(
                    provider_profile_for_key(key), access_mode=access_mode
                )
                for key in provider_keys
            ]
        )

    async def inspect(
        self,
        url: str,
        *,
        access_context: ProviderAccessContextRef | None = None,
        deadline_at: datetime | None = None,
        allow_session_fallback: bool = True,
    ) -> InspectResponse:
        safe_url = safe_media_url(url)
        source = provider_request(safe_url)
        await self._require_companion(source.profile.key)
        context = (
            await self._sessions.context_for(source.profile, url=safe_url)
            if access_context is None
            else await self._sessions.validate_context(
                source.profile, access_context, url=safe_url
            )
        )
        timeout = self._settings.runner_inspect_timeout_seconds
        if deadline_at is not None:
            timeout = min(timeout, (deadline_at - datetime.now(UTC)).total_seconds())
            if timeout <= 0:
                raise RunnerFailure("inspection_timeout", status=504)
        workspace = self._workspaces.create("inspect")
        try:
            try:
                async with asyncio.timeout(timeout):
                    async with self._sessions.operation(context) as cookie_jar:
                        try:
                            inspection = await self._inspection.inspect(
                                source,
                                workspace,
                                context=context,
                                cookie_jar=cookie_jar,
                            )
                        except RunnerFailure as error:
                            # A login wall, bot challenge or cookie demand hands the
                            # task to the user's own Chrome session without asking.
                            # 429, private content and network failures cannot.
                            if (
                                not allow_session_fallback
                                or error.code not in _SESSION_UPGRADE_CODES
                                or self._settings.runner_access_mode
                                is not ProviderAccessMode.OPERATOR_MANAGED
                                or context.access_mode
                                is not ProviderAccessMode.ANONYMOUS
                                or source.profile.access_policy
                                is not ProviderAccessPolicy.OPERATOR_PUBLIC
                                or ProviderAccessMode.OPERATOR_MANAGED
                                not in source.profile.access_modes
                            ):
                                raise
                            context = await self._sessions.context_for(
                                source.profile,
                                url=safe_url,
                                access_mode=ProviderAccessMode.OPERATOR_MANAGED,
                            )
                            async with self._sessions.operation(context) as account_jar:
                                inspection = await self._inspection.inspect(
                                    source,
                                    workspace,
                                    context=context,
                                    cookie_jar=account_jar,
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
                            egress_proxy=self._settings.egress_proxy_for(
                                context.provider_key
                            ),
                        )
                        return inspect_response(
                            inspection,
                            plans,
                            access_context=context,
                            thumbnail_data_url=thumbnail_data_url,
                        )
            except TimeoutError as exc:
                raise RunnerFailure("inspection_timeout", status=504) from exc
        finally:
            workspace.cleanup()

    async def download(self, request: DownloadRequest) -> DownloadResponse:
        task = asyncio.current_task()
        if task is None:
            raise RunnerFailure("internal_error", status=500)
        self._active.register(request.task_id, task)
        workspace = None
        succeeded = False
        try:
            async with asyncio.timeout(self._settings.runner_download_timeout_seconds):
                safe_url = safe_media_url(request.url)
                source = provider_request(safe_url)
                await self._require_companion(source.profile.key)
                context = await self._sessions.validate_context(
                    source.profile, request.access_context.to_domain(), url=safe_url
                )
                workspace = self._workspaces.create(request.task_id)
                async with self._sessions.operation(context) as cookie_jar:
                    response = await self._download_in_workspace(
                        request,
                        source,
                        workspace,
                        context=context,
                        cookie_jar=cookie_jar,
                    )
            self._active.complete(request.task_id, task)
            succeeded = True
            return response
        except asyncio.CancelledError as exc:
            raise RunnerFailure("cancelled", status=409) from exc
        except TimeoutError as exc:
            raise RunnerFailure("download_timeout", status=504) from exc
        except WorkspaceViolation as exc:
            raise RunnerFailure("workspace_limit_exceeded", status=413) from exc
        finally:
            self._active.discard(request.task_id, task)
            if workspace is not None and not succeeded:
                workspace.cleanup()

    async def _require_companion(self, provider_key: str) -> None:
        base_url = self._settings.runner_youtube_pot_base_url
        if provider_key == "youtube" and base_url is not None:
            await require_youtube_sidecar_identity(base_url)

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

    async def _download_in_workspace(
        self,
        request: DownloadRequest,
        source: ProviderRequest,
        workspace: TaskWorkspace,
        *,
        context: ProviderAccessContextRef,
        cookie_jar: Path | None,
    ) -> DownloadResponse:
        inspection = await self._inspection.inspect(
            source,
            workspace,
            context=context,
            cookie_jar=cookie_jar,
        )
        failure_context = ProviderFailureContext(
            provider_key=source.profile.key,
            source_url=source.source_url,
            authenticated=context.access_mode is ProviderAccessMode.OPERATOR_MANAGED,
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
            legacy_collection_image_fallback = (
                request.media_kind is MediaKind.VIDEO_COLLECTION
                and inspection.media_kind is MediaKind.IMAGE_GALLERY
            )
            if (
                request.media_kind is not inspection.media_kind
                and not legacy_collection_image_fallback
            ) or (request.asset_count != inspection.asset_count):
                raise RunnerFailure("source_changed", status=409)
            if request.media_kind is MediaKind.VIDEO_COLLECTION:
                self._active.update(request.task_id, RunnerTaskStage.DOWNLOADING, 10)
                if inspection.media_kind is MediaKind.IMAGE_GALLERY:
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
                else:
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
        output = workspace.validate_outputs([artifact.name])[0]
        self._active.update(request.task_id, RunnerTaskStage.VERIFYING, 85)
        probe_payload = await self._commands.probe(
            artifact,
            workspace.path,
            failure_context=failure_context,
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
