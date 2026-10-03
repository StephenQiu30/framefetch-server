from __future__ import annotations

import json

from app.integrations.ai_cli.codex_app_server_client import CodexAppServerClient
from app.integrations.ai_cli.codex_app_server_protocol import CodexAppServerInvoker
from app.integrations.ai_cli.config import CliAdapterConfig
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
from app.integrations.ai_cli.screenplay_workspace import (
    prepare_screenplay_call_files,
    prepare_screenplay_job_files,
)
from app.integrations.ai_cli.workspace import JobFiles, run_with_workspace_policy
from app.services.analysis_execution.content_models import ContentModelRequest
from app.services.analysis_execution.models import (
    ScreenplayAnalysisRequest,
    ScreenplayAnalysisSynthesisRequest,
)
from app.services.analysis_execution.screenplay_rewrite_models import (
    ScreenplayGlossaryRequest,
    ScreenplayRewriteChunkRequest,
)


class CodexAppServerScreenplayAnalyzer:
    def __init__(
        self,
        config: CliAdapterConfig,
        *,
        client: CodexAppServerInvoker | None = None,
    ) -> None:
        self._config = config
        self._client = client or CodexAppServerClient(config)

    async def generate_content(self, request: ContentModelRequest) -> object:
        source = request.workspace / "input" / "screenplay.md"
        source.parent.mkdir(mode=0o700, exist_ok=True)
        source.write_text(
            "Content materials are embedded in the fixed request.\n", encoding="utf-8"
        )
        source.chmod(0o600)
        schema = json.loads(request.schema_json)
        files = prepare_screenplay_call_files(
            workspace=request.workspace,
            screenplay=source,
            schema=schema,
            prompt=request.prompt,
            manifest={"call": "content", "stage": request.stage},
        )
        return await self._invoke(files, request.prompt)

    async def analyze(self, request: ScreenplayAnalysisRequest) -> object:
        schema = screenplay_analysis_output_schema(
            request.output_language, request.source_scene_ids
        )
        prompt = screenplay_analysis_prompt(request)
        files = prepare_screenplay_job_files(request, schema, prompt)
        return await self._invoke(files, prompt)

    async def synthesize(self, request: ScreenplayAnalysisSynthesisRequest) -> object:
        schema = screenplay_analysis_summary_output_schema(request.output_language)
        prompt = screenplay_analysis_synthesis_prompt(request)
        files = prepare_screenplay_call_files(
            workspace=request.workspace,
            screenplay=request.screenplay,
            schema=schema,
            prompt=prompt,
            manifest={
                "call": "screenplay-analysis-synthesis",
                "source_language": request.source_language,
                "source_scene_ids": list(request.source_scene_ids),
            },
        )
        return await self._invoke(files, prompt)

    async def build_glossary(self, request: ScreenplayGlossaryRequest) -> object:
        schema = screenplay_glossary_output_schema(
            request.source_language, request.target_language
        )
        prompt = screenplay_glossary_prompt(request)
        files = prepare_screenplay_call_files(
            workspace=request.workspace,
            screenplay=request.screenplay,
            schema=schema,
            prompt=prompt,
            manifest={
                "call": "screenplay-glossary",
                "source_language": request.source_language,
                "target_language": request.target_language,
            },
        )
        return await self._invoke(files, prompt)

    async def rewrite_chunk(self, request: ScreenplayRewriteChunkRequest) -> object:
        schema = screenplay_rewrite_chunk_output_schema(
            source_scene_id=request.source_scene_id,
            part_no=request.part_no,
            source_sha256=request.source_sha256,
            target_language=request.target_language,
        )
        prompt = screenplay_rewrite_chunk_prompt(request)
        files = prepare_screenplay_call_files(
            workspace=request.workspace,
            screenplay=request.screenplay,
            schema=schema,
            prompt=prompt,
            manifest={
                "call": "screenplay-rewrite-chunk",
                "source_scene_id": request.source_scene_id,
                "part_no": request.part_no,
                "source_sha256": request.source_sha256,
                "target_language": request.target_language,
            },
        )
        return await self._invoke(files, prompt)

    async def _invoke(self, files: JobFiles, prompt: str) -> object:
        schema = json.loads(files.schema.read_text(encoding="utf-8"))
        return await run_with_workspace_policy(
            self._client.invoke(
                root=files.root,
                prompt=prompt,
                schema=schema,
                duration_ms=None,
            ),
            root=files.root,
            config=self._config,
        )
