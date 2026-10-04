from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from app.integrations.ai_cli.config import CliAdapterConfig
from app.integrations.ai_cli.errors import AnalysisCliError
from app.integrations.ai_cli.workspace import _validate_workspace, prepare_job_files
from app.services.analysis.rules.model_schema import analysis_output_schema
from tests.unit.integrations.ai_cli.helpers import request


def config() -> CliAdapterConfig:
    return CliAdapterConfig(
        binary=Path(sys.executable),
        model="controlled-model",
        ffmpeg=Path(sys.executable),
        ffprobe=Path(sys.executable),
    )


def prepared_workspace(tmp_path: Path) -> Path:
    analysis_request = request(tmp_path)
    schema = analysis_output_schema("zh-CN")
    return prepare_job_files(analysis_request, schema, "controlled prompt").root


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is POSIX-only")
def test_runtime_fifo_is_allowed_only_in_tmp(tmp_path: Path) -> None:
    root = prepared_workspace(tmp_path)
    os.mkfifo(root / "tmp" / "cli.sock")

    _validate_workspace(root, config())

    os.mkfifo(root / "work" / "untrusted.fifo")
    with pytest.raises(AnalysisCliError, match="analysis_resource_limit"):
        _validate_workspace(root, config())


def test_workspace_rejects_symlinks(tmp_path: Path) -> None:
    root = prepared_workspace(tmp_path)
    (root / "work" / "escape").symlink_to(Path.home())

    with pytest.raises(AnalysisCliError, match="analysis_resource_limit"):
        _validate_workspace(root, config())
