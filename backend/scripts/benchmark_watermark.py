"""Reproduce the local VSR/FFmpeg comparison; never overwrite the source.

Run in a separate Python 3.12 environment with the pinned VSR checkout and its
STTN dependencies. This is an experiment, not the production job executor.
Video timestamps are supplied explicitly; audio is copied from the source and
checked after decoding. No platform URL or credentials enter this script.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

VSR_COMMIT = "e109b9ddc1d0e8f153199dfa05c1d767546906d8"
MODEL_SHA256 = "c8408c9dd1300bd7000ea3a81b8236db89d9c0f185837781e38283c1e464675b"


def run(*command: str) -> bytes:
    return subprocess.run(command, check=True, capture_output=True).stdout


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def probe(path: Path) -> dict:
    return json.loads(
        run(
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--method", choices=("vsr", "delogo", "removelogo"), required=True
    )
    parser.add_argument(
        "--region", type=int, nargs=4, metavar=("X", "Y", "W", "H"), required=True
    )
    parser.add_argument("--vsr-root", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--device", choices=("cpu", "mps", "cuda"), default="cpu")
    args = parser.parse_args()
    source, destination = args.input.resolve(), args.output.resolve()
    if source == destination or destination.exists():
        parser.error("output must be a new file distinct from the source")
    info = probe(source)
    videos = [item for item in info["streams"] if item["codec_type"] == "video"]
    if len(videos) != 1:
        parser.error("exactly one video stream is required")
    width, height = videos[0]["width"], videos[0]["height"]
    x, y, w, h = args.region
    if min(x, y) < 0 or min(w, h) < 2 or x + w > width or y + h > height:
        parser.error("region lies outside the encoded frame")
    if videos[0].get("color_transfer") in {"smpte2084", "arib-std-b67"}:
        parser.error("this experiment does not support HDR")
    if any(item.get("rotation", 0) for item in videos[0].get("side_data_list", [])):
        parser.error("normalize display rotation explicitly before this experiment")
    started = time.monotonic()
    initial_hash = digest(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if args.method == "vsr":
        if args.vsr_root is None or args.model is None:
            parser.error("VSR requires --vsr-root and --model")
        revision = (
            run("git", "-C", str(args.vsr_root), "rev-parse", "HEAD").decode().strip()
        )
        if revision != VSR_COMMIT or digest(args.model) != MODEL_SHA256:
            parser.error("VSR checkout or model does not match the experiment")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        sys.path.insert(0, str(args.vsr_root.resolve()))
        import av
        import numpy as np
        import torch
        from backend.inpaint.sttn_auto_inpaint import STTNInpaint

        model = STTNInpaint(torch.device(args.device), str(args.model.resolve()))
        silent = destination.with_suffix(".silent.mp4")
        if silent.exists():
            parser.error("intermediate output already exists")
        with av.open(str(source)) as incoming, av.open(str(silent), "w") as outgoing:
            original = incoming.streams.video[0]
            encoded = outgoing.add_stream("libx264", rate=original.average_rate)
            encoded.width, encoded.height, encoded.pix_fmt = width, height, "yuv420p"
            encoded.time_base = encoded.codec_context.time_base = original.time_base
            encoded.options = {"crf": "18", "preset": "fast"}
            mask = np.zeros((height, width), np.uint8)
            mask[y : y + h, x : x + w] = 255
            frames = incoming.decode(video=0)
            count = 0
            while batch := list(itertools.islice(frames, 50)):
                repaired = model(
                    [frame.to_ndarray(format="bgr24") for frame in batch], mask
                )
                for original_frame, array in zip(batch, repaired, strict=True):
                    frame = av.VideoFrame.from_ndarray(array, format="bgr24")
                    frame.pts, frame.time_base = (
                        original_frame.pts,
                        original_frame.time_base,
                    )
                    for packet in encoded.encode(frame):
                        outgoing.mux(packet)
                count += len(batch)
                print(f"processed {count} frames", flush=True)
            for packet in encoded.encode():
                outgoing.mux(packet)
        run(
            "ffmpeg",
            "-v",
            "error",
            "-n",
            "-i",
            str(silent),
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "1:a?",
            "-c",
            "copy",
            str(destination),
        )
        silent.unlink()
    else:
        if args.method == "delogo":
            # The extra pixels let delogo accept edge-touching regions; black
            # edge artifacts are an evaluated limitation, not a hidden crop.
            filtering = (
                f"pad=iw+4:ih+4:0:0,delogo=x={x}:y={y}:w={w}:h={h},"
                f"crop={width}:{height}:0:0"
            )
        else:
            import cv2
            import numpy as np

            mask_path = destination.with_suffix(".mask.png")
            mask = np.zeros((height, width), np.uint8)
            mask[y : y + h, x : x + w] = 255
            cv2.imwrite(str(mask_path), mask)
            # Run from the output directory; fixed filename avoids filter-path
            # escaping and never interprets a user-provided filter expression.
            os.chdir(destination.parent)
            filtering = f"removelogo={mask_path.name}"
        run(
            "ffmpeg",
            "-v",
            "error",
            "-n",
            "-i",
            str(source),
            "-vf",
            filtering,
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "fast",
            "-fps_mode",
            "passthrough",
            "-c:a",
            "copy",
            str(destination),
        )
    elapsed = time.monotonic() - started
    audio_hashes = []
    for index, _ in enumerate(
        item for item in info["streams"] if item["codec_type"] == "audio"
    ):
        hashes = [
            run(
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(path),
                "-map",
                f"0:a:{index}",
                "-f",
                "hash",
                "-hash",
                "sha256",
                "-",
            )
            .decode()
            .strip()
            for path in (source, destination)
        ]
        if hashes[0] != hashes[1]:
            raise RuntimeError("decoded audio changed")
        audio_hashes.append(hashes[0])
    if digest(source) != initial_hash:
        raise RuntimeError("source changed")
    run("ffmpeg", "-v", "error", "-xerror", "-i", str(destination), "-f", "null", "-")
    evidence = {
        "method": args.method,
        "device": args.device if args.method == "vsr" else "cpu",
        "vsr_commit": VSR_COMMIT if args.method == "vsr" else None,
        "model_sha256": MODEL_SHA256 if args.method == "vsr" else None,
        "input_sha256": initial_hash,
        "output_sha256": digest(destination),
        "region_xywh": args.region,
        "elapsed_seconds": elapsed,
        "max_rss_platform_units": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "decoded_audio_hashes": audio_hashes,
        "input_probe": info,
        "output_probe": probe(destination),
    }
    destination.with_suffix(".json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {key: value for key, value in evidence.items() if not key.endswith("probe")}
        )
    )


if __name__ == "__main__":
    main()
