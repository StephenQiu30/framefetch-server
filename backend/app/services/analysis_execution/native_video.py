"""Run pinned reelbench tools outside the model's read-only boundary."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import shutil
import signal
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.integrations.ai_cli.errors import AnalysisCliError
from app.integrations.object_storage import MinioObjectStorage
from app.services.analysis.models import AnalysisReportArtifactSnapshot
from app.services.analysis.skills.upstream_catalog import UPSTREAM_ROOT, UpstreamCatalog

MAX_SHOTS = 100
MAX_NATIVE_BYTES = 16 * 1024**2
SCRIPT = UPSTREAM_ROOT / "reelbench/skills/video-shots/scripts/video-shots.mjs"


async def run_native(directory: Path, *arguments: str) -> bytes:
    node = shutil.which("node")
    if node is None:
        raise AnalysisCliError("media_dependency_unavailable", no_model_execution=True)
    process = await asyncio.create_subprocess_exec(
        node,
        str(SCRIPT),
        *arguments,
        cwd=directory,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        async with asyncio.timeout(600):
            output, _ = await process.communicate()
        if process.returncode != 0 or len(output) > MAX_NATIVE_BYTES:
            raise AnalysisCliError("invalid_model_output", outcome_known=True)
        return output
    finally:
        if process.returncode is None:
            os.killpg(process.pid, signal.SIGKILL)
            await process.wait()


@dataclass(frozen=True, slots=True)
class MeasuredVideo:
    directory: Path
    document: dict[str, Any]

    @property
    def context(self) -> str:
        return json.dumps(self.document, ensure_ascii=False)


async def measure_video(
    workspace: Path, artifact: Path, language: str, *, max_shots: int = MAX_SHOTS
) -> MeasuredVideo:
    UpstreamCatalog().verify("reelbench")
    root = workspace.resolve(strict=True)
    if artifact.resolve(strict=True) != root / "input/video.bin":
        raise AnalysisCliError("analysis_media_invalid", no_model_execution=True)
    directory = root / "work/reelbench"
    directory.mkdir(parents=True, mode=0o700)
    output = await run_native(
        directory,
        "seed",
        str(artifact),
        "--track",
        "track.json",
        "--title",
        "逐镜拉片" if language == "zh-CN" else "Shot breakdown",
        "--lang",
        "zh" if language == "zh-CN" else "en",
    )
    document = json.loads(output)
    if (
        not isinstance(document, dict)
        or not 1 <= len(document.get("shots", [])) <= max_shots
    ):
        raise AnalysisCliError("analysis_resource_limit", no_model_execution=True)
    (directory / "shots.json").write_bytes(output)
    return MeasuredVideo(directory, document)


async def extract_pairs(measured: MeasuredVideo, artifact: Path) -> None:
    directory = measured.directory
    await run_native(
        directory, "frames", "shots.json", "--video", str(artifact), "--dir", "frames"
    )
    expected = {
        f"{shot['id']}{pick}.jpg"
        for shot in measured.document["shots"]
        for pick in ("a", "b")
    }
    if {path.name for path in (directory / "frames").glob("*.jpg")} != expected:
        raise AnalysisCliError("analysis_media_invalid", no_model_execution=True)
    for pick in ("a", "b"):
        await run_native(
            directory,
            "sheet",
            "shots.json",
            "--dir",
            "frames",
            "--cols",
            "4",
            "--rows",
            "6",
            "--out",
            "sheets",
            "--pick",
            pick,
        )
    if len(tuple((directory / "sheets").glob("*.jpg"))) != 2 * (
        (len(expected) // 2 + 23) // 24
    ):
        raise AnalysisCliError("analysis_media_invalid", no_model_execution=True)


async def native_reports(measured: MeasuredVideo) -> tuple[str, bytes, bytes]:
    directory = measured.directory
    (directory / "shots.json").write_text(measured.context, encoding="utf-8")
    await run_native(
        directory,
        "validate",
        "shots.json",
        "--track",
        "track.json",
        "--frames",
        "frames",
    )
    common = ("shots.json", "--track", "track.json", "--frames", "frames")
    markdown = await run_native(directory, "render", *common, "--md")
    html = await run_native(directory, "render", *common, "--html")
    (directory / "report.md").write_bytes(markdown)
    (directory / "report.html").write_bytes(html)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(directory.rglob("*")):
            if path.is_file() and not path.name.startswith("."):
                info = zipfile.ZipInfo(path.relative_to(directory).as_posix())
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                bundle.writestr(info, path.read_bytes())
        bundle.writestr(
            "SOURCE.txt",
            "reelbench 1b51af897b6a57556b85dfe96e0427e231b4b613\n"
            "Original video excluded; use the report local file picker.\n",
        )
    if len(buffer.getvalue()) > MAX_NATIVE_BYTES:
        raise AnalysisCliError("analysis_resource_limit", outcome_known=True)
    return markdown.decode("utf-8"), html, buffer.getvalue()


async def save_native_bundle(
    storage: MinioObjectStorage, job_id: str, run_id: str, content: bytes
) -> AnalysisReportArtifactSnapshot:
    digest = hashlib.sha256(content).hexdigest()
    key = f"analyses/{job_id}/runs/{run_id}/native/{digest}.zip"
    current = await storage.stat(key)
    if current is None:
        await storage.upload_bytes(key, content, "application/zip", digest)
        current = await storage.stat(key)
    if current is None or (current.size_bytes, current.sha256) != (
        len(content),
        digest,
    ):
        raise AnalysisCliError("artifact_integrity_failed", outcome_known=True)
    return AnalysisReportArtifactSnapshot(
        "zip", key, "application/zip", len(content), digest
    )
