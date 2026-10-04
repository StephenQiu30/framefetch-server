from __future__ import annotations

import base64
import json
from typing import Any

from app.integrations.ai_api.client import (
    StructuredModel,
    invoke_structured,
)
from app.integrations.ai_api.config import ApiAdapterConfig
from app.integrations.ai_api.frames import ApiFrameExtractor, FrameEvidence
from app.integrations.ai_cli.prompt import analysis_prompt
from app.integrations.ai_cli.screenplay_prompt import (
    screenplay_analysis_prompt,
    screenplay_analysis_synthesis_prompt,
)
from app.integrations.ai_cli.screenplay_rewrite_prompt import (
    screenplay_glossary_prompt,
    screenplay_rewrite_chunk_prompt,
)
from app.integrations.ai_cli.screenplay_rewrite_schema import (
    screenplay_glossary_output_schema,
    screenplay_rewrite_chunk_output_schema,
)
from app.integrations.ai_cli.screenplay_schema import (
    screenplay_analysis_output_schema,
    screenplay_analysis_summary_output_schema,
)
from app.integrations.ai_cli.workspace import (
    prepare_job_files,
    run_with_workspace_policy,
)
from app.services.analysis.rules.model_schema import analysis_output_schema
from app.services.analysis_execution.content_models import ContentModelRequest
from app.services.analysis_execution.models import (
    ScreenplayAnalysisRequest,
    ScreenplayAnalysisSynthesisRequest,
    VideoAnalysisRequest,
)
from app.services.analysis_execution.screenplay_rewrite_models import (
    ScreenplayGlossaryRequest,
    ScreenplayRewriteChunkRequest,
)


class ApiAnalyzer:
    supports_creation_images = True

    def __init__(
        self,
        config: ApiAdapterConfig,
        *,
        model: StructuredModel,
        frames: ApiFrameExtractor | None = None,
    ) -> None:
        self._config = config
        self._model = model
        self._frames = frames or ApiFrameExtractor(config)

    async def generate_content(self, request: ContentModelRequest) -> object:
        if request.image_paths:
            content: list[dict[str, Any]] = [{"type": "text", "text": request.prompt}]
            if len(request.image_paths) > 12:
                raise ValueError("creation image limit")
            for path in request.image_paths:
                if (
                    path.is_symlink()
                    or not path.resolve().is_relative_to(request.workspace)
                    or path.stat().st_size > self._config.max_image_bytes
                ):
                    raise ValueError("invalid creation frame")
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,"
                            + base64.b64encode(path.read_bytes()).decode(),
                        },
                    }
                )
            return await self._invoke(
                request.prompt, json.loads(request.schema_json), content
            )
        return await self._invoke(request.prompt, json.loads(request.schema_json))

    async def analyze(self, request: VideoAnalysisRequest) -> object:
        schema = (
            json.loads(request.schema_json)
            if request.schema_json
            else analysis_output_schema(
                request.output_language, request.result_contract
            )
        )
        prompt = analysis_prompt(
            request,
            ffmpeg=str(self._config.ffmpeg),
            ffprobe=str(self._config.ffprobe),
            provided_frames=True,
        )
        files = prepare_job_files(request, schema, prompt)

        async def operation() -> dict[str, Any]:
            evidence = await self._frames.extract(
                request.artifact,
                workspace=files.root,
                duration_ms=request.duration_ms,
                observation_ms=request.observation_ms,
            )
            return await self._invoke(prompt, schema, _frame_content(prompt, evidence))

        return await run_with_workspace_policy(
            operation(), root=files.root, config=self._config
        )

    async def analyze_screenplay(self, request: ScreenplayAnalysisRequest) -> object:
        return await self._invoke(
            screenplay_analysis_prompt(request),
            screenplay_analysis_output_schema(
                request.output_language, request.source_scene_ids
            ),
        )

    async def synthesize_screenplay_analysis(
        self, request: ScreenplayAnalysisSynthesisRequest
    ) -> object:
        return await self._invoke(
            screenplay_analysis_synthesis_prompt(request),
            screenplay_analysis_summary_output_schema(request.output_language),
        )

    async def build_screenplay_glossary(
        self, request: ScreenplayGlossaryRequest
    ) -> object:
        return await self._invoke(
            screenplay_glossary_prompt(request),
            screenplay_glossary_output_schema(
                request.source_language, request.target_language
            ),
        )

    async def rewrite_screenplay_chunk(
        self, request: ScreenplayRewriteChunkRequest
    ) -> object:
        return await self._invoke(
            screenplay_rewrite_chunk_prompt(request),
            screenplay_rewrite_chunk_output_schema(
                source_scene_id=request.source_scene_id,
                part_no=request.part_no,
                source_sha256=request.source_sha256,
                target_language=request.target_language,
            ),
        )

    async def _invoke(
        self,
        prompt: str,
        schema: dict[str, Any],
        content: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return await invoke_structured(
            self._model,
            prompt=prompt,
            schema=schema,
            content=content,
            timeout_seconds=self._config.timeout_seconds,
            maximum_result_bytes=self._config.max_stdout_bytes,
        )


def _frame_content(
    prompt: str, evidence: tuple[FrameEvidence, ...]
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for index, frame in enumerate(evidence, start=1):
        content.extend(
            (
                {
                    "type": "text",
                    "text": f"截图 {index} · {frame.timestamp_ms} ms（按时间顺序）",
                },
                {"type": "image_url", "image_url": {"url": frame.data_url}},
            )
        )
    return content
