from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.integrations.ai_cli.errors import AnalysisCliError
from app.services.analysis.skills.upstream_catalog import (
    MAX_RESOURCE_BYTES,
    RESOURCE_POLICY,
    UpstreamCatalog,
    frozen_packages,
)

MAX_READS = 32
MAX_TOTAL_BYTES = 1024 * 1024
TOOL = {
    "name": "read_skill_resource",
    "description": (
        "Read entire pinned Markdown from this call's frozen Skill. "
        "Read-only, no shell, network, or user files."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "package_id": {"type": "string"},
            "path": {"type": "string"},
        },
        "required": ["package_id", "path"],
        "additionalProperties": False,
    },
    "annotations": {"readOnlyHint": True, "openWorldHint": False},
}


class SkillResources:
    def __init__(
        self, workspace: Path, *, catalog: UpstreamCatalog | None = None
    ) -> None:
        self.workspace = workspace.resolve(strict=True)
        path = self.workspace / RESOURCE_POLICY
        if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size > 8192:
            raise ValueError("invalid upstream resource policy")
        self.packages = frozen_packages(
            "\n<framefetch_upstream_packages>\n"
            + path.read_text(encoding="utf-8")
            + "\n</framefetch_upstream_packages>"
        )
        self.catalog = catalog or UpstreamCatalog()
        for package_id, fingerprint in self.packages.items():
            if self.catalog.verify(package_id).fingerprint != fingerprint:
                raise ValueError("upstream snapshot mismatch")
        self.reads = 0
        self.bytes_read = 0

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if name != TOOL["name"] or set(arguments) != {"package_id", "path"}:
                raise ValueError("unknown skill resource request")
            package_id, relative = arguments["package_id"], arguments["path"]
            if not isinstance(package_id, str) or not isinstance(relative, str):
                raise ValueError("invalid skill resource request")
            if package_id not in self.packages:
                raise ValueError("package is outside this call's frozen Skill")
            if self.reads >= MAX_READS:
                raise ValueError("skill resource read limit")
            text = self.catalog.read_markdown(package_id, relative)
            size = len(text.encode("utf-8"))
            if size > MAX_RESOURCE_BYTES or self.bytes_read + size > MAX_TOTAL_BYTES:
                raise ValueError("skill resource byte limit")
            receipt = {
                "package_id": package_id,
                "path": relative,
                "sha256": dict(self.catalog.packages[package_id].files)[relative],
                "size_bytes": size,
            }
            directory = self.workspace / "work"
            path = directory / "skill-resource-receipts.jsonl"
            if directory.is_symlink() or path.is_symlink():
                raise ValueError("invalid skill resource receipt path")
            directory.mkdir(mode=0o700, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(receipt, ensure_ascii=False) + "\n")
            path.chmod(0o600)
            self.reads += 1
            self.bytes_read += size
            return {"content": [{"type": "text", "text": text}]}
        except (OSError, ValueError) as exc:
            return {"isError": True, "content": [{"type": "text", "text": str(exc)}]}


def reject_unsupported_resources(instructions: str) -> None:
    if frozen_packages(instructions):
        raise AnalysisCliError("analysis_cli_unsupported", no_model_execution=True)
