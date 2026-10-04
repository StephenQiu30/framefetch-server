"""Bounded receipts for successful video observations, without model content."""

import hashlib
import json
from pathlib import Path


def record_observation(
    root: Path,
    tool: str,
    *,
    timestamps_ms: list[int],
    image: bytes | None = None,
) -> None:
    manifest = json.loads((root / "input" / "manifest.json").read_text())
    path = root / "work" / "video-observations.jsonl"
    if path.exists() and path.stat().st_size >= 512 * 1024:
        raise ValueError("observation receipt budget reached")
    receipt = {
        "tool": tool,
        "stage": manifest.get("stage", "draft"),
        "timestamps_ms": timestamps_ms,
        "position_kind": "requested_near_frame_or_sampling_estimate",
        "image_sha256": hashlib.sha256(image).hexdigest() if image else None,
        "image_size_bytes": len(image) if image else 0,
    }
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(receipt, sort_keys=True) + "\n")
