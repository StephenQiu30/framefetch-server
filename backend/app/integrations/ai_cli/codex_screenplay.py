from __future__ import annotations

import json
from pathlib import Path

from app.integrations.ai_cli.codex_app_server_client import CodexAppServerClient
from app.integrations.ai_cli.codex_app_server_protocol import CodexAppServerInvoker
from app.integrations.ai_cli.config import CliAdapterConfig
from app.integrations.ai_cli.errors import AnalysisCliError
from app.integrations.ai_cli.screenplay_prompt import (
    screenplay_analysis_prompt,
    screenplay_analysis_synthesis_prompt,
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
        return await self._invoke(files, request.prompt, request.image_paths)

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
            skill_instructions=request.skill_instructions,
            manifest={
                "call": "screenplay-analysis-synthesis",
                "source_language": request.source_language,
                "source_scene_ids": list(request.source_scene_ids),
            },
        )
        return await self._invoke(files, prompt)

    async def _invoke(
        self, files: JobFiles, prompt: str, image_paths: tuple[Path, ...] = ()
    ) -> object:
        schema = json.loads(files.schema.read_text(encoding="utf-8"))
        if image_paths:
            for path in image_paths:
                if path.is_symlink() or not path.resolve().is_relative_to(files.root):
                    raise AnalysisCliError(
                        "artifact_integrity_failed", no_model_execution=True
                    )
            return await run_with_workspace_policy(
                self._client.invoke(
                    root=files.root,
                    prompt=prompt,
                    schema=schema,
                    duration_ms=None,
                    image_paths=image_paths,
                ),
                root=files.root,
                config=self._config,
            )
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
