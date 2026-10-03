from __future__ import annotations


class AnalysisCliError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        no_model_execution: bool = False,
        outcome_known: bool = False,
    ) -> None:
        self.code = code
        self.no_model_execution = no_model_execution
        self.outcome_known = outcome_known
        super().__init__(code)


def classify_cli_failure(output: bytes) -> AnalysisCliError:
    detail = output.decode("utf-8", errors="ignore").lower()
    if "failed to load agents.md instructions" in detail:
        return AnalysisCliError("analysis_sandbox_unavailable")
    if "invalid_json_schema" in detail:
        return AnalysisCliError("analysis_cli_unsupported")
    if any(marker in detail for marker in ("429", "rate limit", "too many requests")):
        return AnalysisCliError("analysis_provider_rate_limited")
    if any(marker in detail for marker in ("credit", "usage limit", "quota")):
        return AnalysisCliError("analysis_provider_usage_limited")
    if any(marker in detail for marker in ("login", "auth", "unauthorized")):
        return AnalysisCliError("analysis_cli_not_authenticated")
    sandbox_markers = (
        "sandbox unavailable",
        "sandbox required but unavailable",
        "sandbox is unavailable",
        "failed to initialize sandbox",
        "failed to start sandbox",
        "sandbox initialization failed",
        "unable to apply sandbox",
        "cannot enforce sandbox",
    )
    if any(marker in detail for marker in sandbox_markers):
        return AnalysisCliError("analysis_sandbox_unavailable")
    turn_markers = ("max turns", "max_turns", "error_max_turns")
    if any(marker in detail for marker in turn_markers):
        return AnalysisCliError("analysis_resource_limit")
    return AnalysisCliError("analysis_cli_failed")
