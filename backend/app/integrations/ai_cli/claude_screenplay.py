from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.integrations.ai_cli.config import CliAdapterConfig
from app.integrations.ai_cli.environment import child_environment
from app.integrations.ai_cli.errors import AnalysisCliError, classify_cli_failure
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
from app.integrations.ai_cli.skill_resources import reject_unsupported_resources
from app.integrations.ai_cli.workspace import run_with_workspace_policy
from app.services.analysis_execution.content_models import ContentModelRequest
from app.services.analysis_execution.models import (
    ScreenplayAnalysisRequest,
    ScreenplayAnalysisSynthesisRequest,
)
from app.workers.runner.process import ProcessSupervisor, ProcessTimeoutError

_MAX_SCHEMA_BYTES = 28_000


class ClaudeCliScreenplayAnalyzer:
    def __init__(
        self,
        config: CliAdapterConfig,
        *,
        supervisor: ProcessSupervisor | None = None,
    ) -> None:
        self._config = config
        self._supervisor = supervisor or ProcessSupervisor(
            stdout_limit_bytes=config.max_stdout_bytes,
            stderr_limit_bytes=config.max_stderr_bytes,
            terminate_grace_seconds=config.terminate_grace_seconds,
        )

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
        return await self._invoke(
            files.root, files.claude_settings, schema, request.prompt
        )

    async def analyze(self, request: ScreenplayAnalysisRequest) -> object:
        reject_unsupported_resources(request.skill_instructions)
        schema = screenplay_analysis_output_schema(
            request.output_language, request.source_scene_ids
        )
        prompt = screenplay_analysis_prompt(request)
        files = prepare_screenplay_job_files(request, schema, prompt)
        return await self._invoke(files.root, files.claude_settings, schema, prompt)

    async def synthesize(self, request: ScreenplayAnalysisSynthesisRequest) -> object:
        reject_unsupported_resources(request.skill_instructions)
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
        return await self._invoke(files.root, files.claude_settings, schema, prompt)

    async def _invoke(
        self,
        root: Path,
        settings: Path,
        schema: dict[str, Any],
        prompt: str,
    ) -> object:
        schema_json = json.dumps(schema, separators=(",", ":"))
        if len(schema_json.encode()) > _MAX_SCHEMA_BYTES:
            raise AnalysisCliError("analysis_resource_limit")
        environment = child_environment(self._config, root)
        environment["CLAUDE_CODE_SKIP_PROMPT_HISTORY"] = "1"
        try:
            result = await run_with_workspace_policy(
                self._supervisor.run(
                    self._argv(settings, schema_json),
                    cwd=root,
                    timeout_seconds=self._config.timeout_seconds,
                    env=environment,
                    input_bytes=prompt.encode(),
                ),
                root=root,
                config=self._config,
            )
        except ProcessTimeoutError as exc:
            raise AnalysisCliError("analysis_cli_timeout") from exc
        except OSError as exc:
            raise AnalysisCliError("analysis_cli_unavailable") from exc
        if result.returncode != 0:
            raise classify_cli_failure(result.stderr + result.stdout)
        if result.stdout_truncated:
            raise AnalysisCliError("analysis_resource_limit")
        try:
            wrapper = json.loads(result.stdout)
            return wrapper["structured_output"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise AnalysisCliError("invalid_model_output") from exc

    def _argv(
        self,
        settings: Path,
        schema_json: str,
    ) -> tuple[str, ...]:
        return (
            str(self._config.binary),
            "--safe-mode",
            "-p",
            "--no-session-persistence",
            "--no-chrome",
            "--disable-slash-commands",
            "--strict-mcp-config",
            "--settings",
            str(settings),
            "--tools",
            "",
            "--disallowedTools",
            "Bash,Read,Write,Edit,WebFetch,WebSearch,Agent",
            "--permission-mode",
            "dontAsk",
            "--model",
            self._config.model,
            "--max-turns",
            "1",
            "--output-format",
            "json",
            "--json-schema",
            schema_json,
        )
