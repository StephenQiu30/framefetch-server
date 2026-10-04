"""Host-only content analysis using fixed materials and durable budget state."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from app.core.config import Settings
from app.integrations.ai_cli.errors import AnalysisCliError
from app.repositories.creation import CreationRepository
from app.schemas.creation import CreationTaskResponse
from app.services.analysis_execution.content_models import ContentModelRequest
from app.services.analysis_execution.models import (
    AnalysisArtifactSource,
    LocalAnalysisArtifact,
)
from app.services.analysis_execution.ports import AnalyzerResolver
from app.services.creation.catalog import get_capability
from app.services.creation.execution import (
    CreationAnalysisOutput,
    CreationOutput,
    creation_prompt,
    execute_deterministic,
    validate_model_output,
)
from app.services.creation.frame_preview import frame_preview
from app.services.creation.media import (
    extract_representative_frame,
    probe_video,
    study_shots,
)
from app.workers.analysis.artifacts import LocalAnalysisArtifactLoader
from app.workers.analysis.creation_workflow import CreationCommand
from temporalio import activity
from temporalio.exceptions import ApplicationError


class ContentGenerator(Protocol):
    async def generate_content(self, request: ContentModelRequest) -> object: ...


class CreationActivities:
    def __init__(
        self,
        repository: CreationRepository,
        resolver: AnalyzerResolver,
        loader: LocalAnalysisArtifactLoader,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.resolver = resolver
        self.loader = loader
        self.settings = settings
        self._model_slot = asyncio.Semaphore(1)
        self._local_slots = asyncio.Semaphore(4)

    @activity.defn(name="run_creation")
    async def run(self, command: CreationCommand) -> str:
        task_id = UUID(command.task_id)
        worker_id = command.workflow_id
        heartbeat = asyncio.create_task(
            self._heartbeat(task_id, asyncio.current_task())
        )
        slot: asyncio.Semaphore | None = None
        try:
            waiting = await self.repository.get_task(task_id)
            if waiting.attempt != command.attempt:
                return "superseded"
            if waiting.status.value != "queued":
                # Preserve the existing duplicate/lost-call claim guard.
                await self.repository.claim_task(
                    task_id, worker_id, expected_attempt=command.attempt
                )
                return (await self.repository.get_task(task_id)).status.value
            candidate_slot = (
                self._model_slot if _needs_model(waiting) else self._local_slots
            )
            # Waiting keeps the durable task queued and reserves no model call.
            # Heartbeats and cancellation remain live while a slot is occupied.
            await candidate_slot.acquire()
            slot = candidate_slot
            claimed = await self.repository.claim_task(
                task_id, worker_id, expected_attempt=command.attempt
            )
            if claimed is None:
                return (await self.repository.get_task(task_id)).status.value
            task = cast(CreationTaskResponse, claimed["task"])
            materials = cast(list[dict[str, object]], claimed["materials"])
            capability = get_capability(task.skill_id)
            if capability.method_sha256 != claimed["method_sha256"]:
                raise ValueError("pinned method version is unavailable")
            async with asyncio.timeout(task.budget.timeout_seconds):
                if capability.execution_kind == "media":
                    output = await self._media(task, materials)
                elif _needs_model(task):
                    output = await self._model(task, materials, worker_id)
                else:
                    output = await asyncio.to_thread(
                        execute_deterministic, task.skill_id, materials, task.options
                    )
            result = await self.repository.finish_task(
                task_id, worker_id, output.text, output.data, output.limitations
            )
            return result.status.value
        except AnalysisCliError as error:
            if error.no_model_execution:
                await self.repository.settle_call(
                    task_id, worker_id, known=True, executed=False
                )
            elif error.outcome_known:
                await self.repository.settle_call(task_id, worker_id, known=True)
            result = await self.repository.fail_task(
                task_id,
                worker_id,
                error.code,
                outcome_unknown=not error.no_model_execution
                and not error.outcome_known,
            )
            return result.status.value
        except asyncio.CancelledError:
            await asyncio.shield(
                self.repository.fail_task(task_id, worker_id, "analysis_cancelled")
            )
            raise
        except (ValueError, TimeoutError):
            result = await self.repository.fail_task(
                task_id, worker_id, "creation_execution_failed"
            )
            return result.status.value
        except Exception:
            raise ApplicationError("creation infrastructure unavailable") from None
        finally:
            if slot is not None:
                slot.release()
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    @activity.defn(name="reconcile_creation")
    async def reconcile(self, command: CreationCommand) -> str:
        task = await self.repository.get_task(UUID(command.task_id))
        if task.attempt != command.attempt:
            return "superseded"
        result = await self.repository.fail_task(
            task.id, command.workflow_id, "analysis_worker_lost"
        )
        return result.status.value

    async def _heartbeat(self, task_id: UUID, parent: asyncio.Task[str] | None) -> None:
        while True:
            activity.heartbeat()
            task = await self.repository.get_task(task_id)
            if task.status.value == "cancelled":
                if parent is not None:
                    parent.cancel()
                return
            await asyncio.sleep(5)

    async def _model(
        self,
        task: CreationTaskResponse,
        materials: list[dict[str, object]],
        worker_id: str,
    ) -> CreationOutput:
        selection = await self.resolver.resolve()
        if not callable(getattr(selection.analyzer, "generate_content", None)):
            raise AnalysisCliError("analysis_cli_unsupported", no_model_execution=True)
        videos = [material for material in materials if material["kind"] == "video"]
        if videos and not getattr(
            selection.analyzer, "supports_creation_images", False
        ):
            raise AnalysisCliError(
                "creation_visual_model_required", no_model_execution=True
            )
        prompt = creation_prompt(task.skill_id, materials, task.options)
        root = self.settings.analysis_workspace_root
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        workspace = Path(tempfile.mkdtemp(prefix="creation-", dir=root))
        workspace.chmod(0o700)
        try:
            image_paths: list[Path] = []
            frames: list[dict[str, object]] = []
            for material in videos:
                local = await self._load_video(task, material)
                try:
                    metadata = await probe_video(
                        local.artifact, self.settings.analysis_ffprobe_binary
                    )
                    begin = int(str(metadata.get("video_start_ms", 0)))
                    end = int(
                        str(metadata.get("video_end_ms", metadata["duration_ms"]))
                    )
                    for index in range(6):
                        if len(image_paths) >= 12:
                            break
                        timestamp = begin + (end - begin) * (2 * index + 1) // 12
                        path = workspace / f"frame-{len(image_paths) + 1}.png"
                        await extract_representative_frame(
                            local.artifact,
                            path,
                            timestamp_ms=timestamp,
                            ffmpeg=self.settings.analysis_ffmpeg_binary,
                            ffprobe=self.settings.analysis_ffprobe_binary,
                        )
                        image_paths.append(path)
                        frames.append(
                            {
                                "id": f"frame-{len(image_paths)}",
                                "material_id": str(material["id"]),
                                "timestamp_ms": timestamp,
                                "material_revision_sha256": str(material["sha256"]),
                                **await asyncio.to_thread(frame_preview, path),
                            }
                        )
                finally:
                    await self.loader.cleanup(local)
            if frames:
                prompt += (
                    "\n附带真实帧按此顺序排列，仅对已提供帧作观察。不要对未采样时段作"
                    "全片结论，不推断未提供的声音；逐项填写media_evidence。\n"
                    + json.dumps(
                        [
                            {
                                key: value
                                for key, value in frame.items()
                                if not key.startswith("preview_")
                            }
                            for frame in frames
                        ],
                        ensure_ascii=False,
                    )
                )
            request = ContentModelRequest(
                workspace=workspace,
                prompt=prompt,
                schema_json=json.dumps(CreationAnalysisOutput.model_json_schema()),
                provider_binding_sha256=selection.binding_sha256,
                stage=task.skill_id,
                image_paths=tuple(image_paths),
            )
            await self.repository.mark_call_sent(task.id, worker_id)
            value = await cast(ContentGenerator, selection.analyzer).generate_content(
                request
            )
            await self.repository.settle_call(task.id, worker_id, known=True)
            output = validate_model_output(
                value, materials, frames, skill_id=task.skill_id
            )
            return CreationOutput(
                output.text,
                {
                    **output.data,
                    "provider": selection.provider,
                    "model": selection.model,
                    "method_sha256": get_capability(task.skill_id).method_sha256,
                    "frames": frames,
                },
                [
                    *output.limitations,
                    "当前模型适配器不提供已审计Token/金额回执；未声称费用已核账。",
                    *(
                        ["画面分析限于实际抽样帧；不代表全片、运动或声音已完整核查。"]
                        if frames
                        else []
                    ),
                ],
            )
        finally:
            await asyncio.to_thread(shutil.rmtree, workspace)

    async def _media(
        self, task: CreationTaskResponse, materials: list[dict[str, object]]
    ) -> CreationOutput:
        material = next((item for item in materials if item["kind"] == "video"), None)
        if material is None or not isinstance(material.get("source"), dict):
            raise ValueError("owned video is required")
        local = await self._load_video(task, material)
        try:
            output = await study_shots(
                local.artifact,
                self.settings.analysis_ffmpeg_binary,
                self.settings.analysis_ffprobe_binary,
            )
            frames: list[dict[str, object]] = []
            shots = cast(list[dict[str, object]], output.data["shots"])
            with tempfile.TemporaryDirectory(
                prefix="frames-", dir=local.artifact.parent
            ) as directory:
                for shot in shots[:12]:
                    timestamp = (
                        int(str(shot["start_ms"])) + int(str(shot["end_ms"]))
                    ) // 2
                    path = Path(directory) / f"frame-{len(frames) + 1}.png"
                    await extract_representative_frame(
                        local.artifact,
                        path,
                        timestamp_ms=timestamp,
                        ffmpeg=self.settings.analysis_ffmpeg_binary,
                        ffprobe=self.settings.analysis_ffprobe_binary,
                    )
                    frames.append(
                        {
                            "id": f"frame-{len(frames) + 1}",
                            "shot_id": shot["id"],
                            "material_id": str(material["id"]),
                            "timestamp_ms": timestamp,
                            "material_revision_sha256": str(material["sha256"]),
                            **await asyncio.to_thread(frame_preview, path),
                        }
                    )
            return CreationOutput(
                output.text, {**output.data, "frames": frames}, output.limitations
            )
        finally:
            await self.loader.cleanup(local)

    async def _load_video(
        self, task: CreationTaskResponse, material: dict[str, object]
    ) -> LocalAnalysisArtifact:
        source = cast(dict[str, object], material["source"])
        artifact = AnalysisArtifactSource(
            artifact_id=UUID(str(material["artifact_id"])),
            bucket=str(source["bucket"]),
            object_key=str(source["object_key"]),
            sha256=str(source["sha256"]),
            size_bytes=int(str(source["size_bytes"])),
            duration_ms=int(str(source["duration_ms"])),
            container="mp4",
        )
        return await self.loader.materialize(
            artifact, job_id=task.id, attempt=task.attempt
        )


def _needs_model(task: CreationTaskResponse) -> bool:
    return get_capability(task.skill_id).execution_kind == "model" or (
        task.skill_id == "article-edit"
        and task.options.get("mode", "format") != "format"
    )
