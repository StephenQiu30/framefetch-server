from __future__ import annotations

import json
from pathlib import Path

from app.integrations.ai_cli.claude_screenplay import ClaudeCliScreenplayAnalyzer
from app.integrations.ai_cli.config import CliAdapterConfig
from app.integrations.ai_cli.environment import child_environment
from app.integrations.ai_cli.errors import AnalysisCliError, classify_cli_failure
from app.integrations.ai_cli.prompt import analysis_prompt
from app.integrations.ai_cli.schema import analysis_output_schema
from app.integrations.ai_cli.workspace import (
    prepare_job_files,
    run_with_workspace_policy,
)
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
from app.workers.runner.process import ProcessSupervisor, ProcessTimeoutError


class ClaudeCliVideoAnalyzer:
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
        self._screenplay = ClaudeCliScreenplayAnalyzer(
            config, supervisor=self._supervisor
        )

    async def generate_content(self, request: ContentModelRequest) -> object:
        return await self._screenplay.generate_content(request)

    async def analyze(self, request: VideoAnalysisRequest) -> object:
        schema = analysis_output_schema(
            request.output_language, request.result_contract
        )
        prompt = analysis_prompt(
            request,
            ffmpeg=str(self._config.ffmpeg),
            ffprobe=str(self._config.ffprobe),
        )
        files = prepare_job_files(request, schema, prompt)
        environment = child_environment(self._config, files.root)
        environment["CLAUDE_CODE_SKIP_PROMPT_HISTORY"] = "1"
        try:
            result = await run_with_workspace_policy(
                self._supervisor.run(
                    self._argv(files.root, files.claude_settings, schema),
                    cwd=files.root,
                    timeout_seconds=self._config.timeout_seconds,
                    env=environment,
                    input_bytes=prompt.encode(),
                ),
                root=files.root,
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
            structured = wrapper["structured_output"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise AnalysisCliError("invalid_model_output") from exc
        return structured

    async def analyze_screenplay(self, request: ScreenplayAnalysisRequest) -> object:
        return await self._screenplay.analyze(request)

    async def synthesize_screenplay_analysis(
        self, request: ScreenplayAnalysisSynthesisRequest
    ) -> object:
        return await self._screenplay.synthesize(request)

    async def build_screenplay_glossary(
        self, request: ScreenplayGlossaryRequest
    ) -> object:
        return await self._screenplay.build_glossary(request)

    async def rewrite_screenplay_chunk(
        self, request: ScreenplayRewriteChunkRequest
    ) -> object:
        return await self._screenplay.rewrite_chunk(request)

    def _argv(
        self,
        root: Path,
        settings: Path,
        schema: dict[str, object],
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
            "Bash,Read",
            "--permission-mode",
            "dontAsk",
            "--allowedTools",
            f"Read({root / 'input' / 'manifest.json'})",
            "--allowedTools",
            f"Read({root / 'work'}/**)",
            "--allowedTools",
            f"Bash({self._config.ffprobe} *)",
            "--allowedTools",
            f"Bash({self._config.ffmpeg} *)",
            "--model",
            self._config.model,
            "--max-turns",
            str(self._config.max_turns),
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(schema, separators=(",", ":")),
        )
