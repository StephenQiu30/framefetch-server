from __future__ import annotations

import json

from app.integrations.ai_cli.codex_app_server_client import CodexAppServerClient
from app.integrations.ai_cli.codex_app_server_protocol import CodexAppServerInvoker
from app.integrations.ai_cli.codex_screenplay import CodexAppServerScreenplayAnalyzer
from app.integrations.ai_cli.config import CliAdapterConfig
from app.integrations.ai_cli.prompt import analysis_prompt
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


class CodexAppServerVideoAnalyzer:
    supports_skill_images = True

    def __init__(
        self,
        config: CliAdapterConfig,
        *,
        client: CodexAppServerInvoker | None = None,
    ) -> None:
        self._config = config
        self._client = client or CodexAppServerClient(config)
        self._screenplay = CodexAppServerScreenplayAnalyzer(config, client=self._client)

    async def generate_content(self, request: ContentModelRequest) -> object:
        return await self._screenplay.generate_content(request)

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
            video_observer=not bool(request.image_paths),
            provided_frames=bool(request.image_paths),
        )
        files = prepare_job_files(request, schema, prompt)
        return await run_with_workspace_policy(
            self._client.invoke(
                root=files.root,
                prompt=prompt,
                schema=schema,
                duration_ms=request.duration_ms,
                image_paths=request.image_paths,
            ),
            root=files.root,
            config=self._config,
        )

    async def analyze_screenplay(self, request: ScreenplayAnalysisRequest) -> object:
        return await self._screenplay.analyze(request)

    async def synthesize_screenplay_analysis(
        self, request: ScreenplayAnalysisSynthesisRequest
    ) -> object:
        return await self._screenplay.synthesize(request)
