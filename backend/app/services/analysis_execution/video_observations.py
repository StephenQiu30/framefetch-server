"""Emit only validated tool receipt metadata before the private workspace is removed."""

import json
import logging
import re
from pathlib import Path

from app.services.analysis.models import AnalysisJobSnapshot

_TOOLS = {
    "probe_video",
    "inspect_video_overview",
    "inspect_video_frame",
    "provided_video_frame",
}
_STAGES = {"plan", "draft", "review", "revise-01", "verify-01"}


def configure_video_observation_logging() -> None:
    logger = logging.getLogger(__name__)
    if not logger.handlers:
        logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)
    logger.propagate = False


def log_video_observations(root: Path, job: AnalysisJobSnapshot) -> None:
    path = root / "work" / "video-observations.jsonl"
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 513 * 1024:
        return
    for line in path.read_text(encoding="utf-8").splitlines()[:1024]:
        try:
            receipt = json.loads(line)
            positions = receipt["timestamps_ms"]
            digest = receipt["image_sha256"]
            size = receipt["image_size_bytes"]
            if (
                receipt["tool"] not in _TOOLS
                or receipt["stage"] not in _STAGES
                or not isinstance(positions, list)
                or len(positions) > 64
                or any(type(value) is not int or value < 0 for value in positions)
                or type(size) is not int
                or not 0 <= size <= 4 * 1024**2
                or (
                    digest is not None and re.fullmatch(r"[0-9a-f]{64}", digest) is None
                )
            ):
                continue
            # A positive receipt means the tool returned bytes, not that the model
            # understood them or that its claimed precise time has been verified.
            logging.getLogger(__name__).info(
                json.dumps(
                    {
                        "event": "skill_video_observation",
                        "job_id": str(job.id),
                        "run_id": str(job.run_id),
                        "source_sha256": job.input_sha256,
                        "tool": receipt["tool"],
                        "stage": receipt["stage"],
                        "timestamps_ms": positions,
                        "image_sha256": digest,
                        "image_size_bytes": size,
                        "position_kind": "requested_near_frame_or_sampling_estimate",
                    },
                    sort_keys=True,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
