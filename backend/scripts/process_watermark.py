"""Isolated STTN process. Operator paths only; one validated local task manifest."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import subprocess
import sys
from pathlib import Path

VSR_COMMIT = "e109b9ddc1d0e8f153199dfa05c1d767546906d8"
MODEL_SHA256 = "c8408c9dd1300bd7000ea3a81b8236db89d9c0f185837781e38283c1e464675b"
MAX_BYTES = 2 * 1024**3


def run(*args: str) -> bytes:
    return subprocess.run(args, check=True, capture_output=True, timeout=300).stdout


def digest(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


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


def frame_timeline(path: Path) -> list:
    data = json.loads(
        run(
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_frames",
            "-show_entries",
            "frame=best_effort_timestamp_time,width,height",
            "-of",
            "json",
            str(path),
        )
    )
    return [
        (f["best_effort_timestamp_time"], f["width"], f["height"])
        for f in data["frames"]
    ]


def validate_input(info: dict) -> dict:
    videos = [s for s in info["streams"] if s["codec_type"] == "video"]
    if len(videos) != 1 or any(
        s["codec_type"] not in {"video", "audio"} for s in info["streams"]
    ):
        raise ValueError("unsupported streams")
    video = videos[0]
    width, height = video["width"], video["height"]
    if (
        width * height > 1920 * 1080
        or min(width, height) < 120
        or width % 2
        or height % 2
    ):
        raise ValueError("unsupported dimensions")
    if video.get("pix_fmt") != "yuv420p" or video.get("color_transfer") in {
        "smpte2084",
        "arib-std-b67",
    }:
        raise ValueError("only 8-bit SDR is supported")
    if video.get("sample_aspect_ratio", "1:1") not in {"1:1", "N/A"}:
        raise ValueError("unsupported pixel aspect ratio")
    if (
        any(s.get("rotation", 0) for s in video.get("side_data_list", []))
        or video.get("tags", {}).get("rotate", "0") != "0"
    ):
        raise ValueError("unsupported display rotation")
    if (
        not 0 < float(info["format"]["duration"]) <= 180
        or abs(float(info["format"].get("start_time", 0))) > 0.05
    ):
        raise ValueError("unsupported timeline")
    if any(
        s["codec_type"] == "audio" and s["codec_name"] != "aac" for s in info["streams"]
    ):
        raise ValueError("only AAC or silent sources are supported")
    return video


def verify(source: Path, output: Path, source_sha: str) -> dict:
    if digest(source) != source_sha or not 0 < output.stat().st_size <= MAX_BYTES:
        raise ValueError("source changed or output exceeds limit")
    before, after = probe(source), probe(output)
    if frame_timeline(source) != frame_timeline(output):
        raise ValueError("video timeline or dimensions changed")
    if (
        abs(float(before["format"]["duration"]) - float(after["format"]["duration"]))
        > 0.1
    ):
        raise ValueError("duration changed")
    audio_before = [s for s in before["streams"] if s["codec_type"] == "audio"]
    audio_after = [s for s in after["streams"] if s["codec_type"] == "audio"]
    if len(audio_before) != len(audio_after):
        raise ValueError("audio streams changed")
    hashes = []
    for i, (a, b) in enumerate(zip(audio_before, audio_after, strict=True)):
        if abs(float(a.get("start_time", 0)) - float(b.get("start_time", 0))) > 0.001:
            raise ValueError("audio alignment changed")
        pair = [
            run(
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(p),
                "-map",
                f"0:a:{i}",
                "-f",
                "hash",
                "-hash",
                "sha256",
                "-",
            )
            for p in (source, output)
        ]
        if pair[0] != pair[1]:
            raise ValueError("decoded audio changed")
        hashes.append(pair[0].decode().strip())
    run("ffmpeg", "-v", "error", "-xerror", "-i", str(output), "-f", "null", "-")
    return {
        "size_bytes": output.stat().st_size,
        "sha256": digest(output),
        "source_sha256": source_sha,
        "audio_hashes": hashes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--vsr-root", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--detector", type=Path, required=True)
    parser.add_argument("--device", choices=["mps", "cuda", "cpu"], required=True)
    args = parser.parse_args()
    root = args.vsr_root.resolve()
    if (
        run("git", "-C", str(root), "rev-parse", "HEAD").decode().strip() != VSR_COMMIT
        or digest(args.model) != MODEL_SHA256
    ):
        raise ValueError("engine verification failed")
    if run("git", "-C", str(root), "diff", "HEAD", "--", "backend").strip():
        raise ValueError("upstream code has been modified")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    sys.path.insert(0, str(root))
    import av
    import numpy as np
    import torch
    from backend.inpaint.sttn_auto_inpaint import STTNInpaint
    from detect_watermark import Detector, matching_boxes, scan

    detector = Detector(args.detector.resolve())
    model = STTNInpaint(torch.device(args.device), str(args.model.resolve()))
    if args.manifest is None:
        # A startup capability probe loads weights before advertising readiness.
        return
    manifest = json.loads(args.manifest.read_text())
    source, output = Path(manifest["source"]), Path(manifest["output"])
    if (
        source.resolve() == output.resolve()
        or output.exists()
        or source.stat().st_size > MAX_BYTES
    ):
        raise ValueError("invalid local input/output")
    original_sha = digest(source)
    if original_sha != manifest["sha256"]:
        raise ValueError("source checksum mismatch")
    info = probe(source)
    try:
        video = validate_input(info)
    except ValueError:
        output.with_suffix(".json").write_text(
            json.dumps(
                {"source_sha256": original_sha, "error_code": "unsupported_media"}
            )
        )
        return
    width, height = video["width"], video["height"]
    samples = scan(source, detector)
    if not any(boxes for _, boxes in samples):
        output.with_suffix(".json").write_text(
            json.dumps({"source_sha256": original_sha, "unchanged": True})
        )
        return
    print(f"detected {sum(bool(boxes) for _, boxes in samples)} samples", flush=True)
    silent = output.with_suffix(".silent.mp4")
    if silent.exists():
        raise ValueError("intermediate file exists")
    with av.open(str(source)) as incoming, av.open(str(silent), "w") as outgoing:
        original = incoming.streams.video[0]
        encoded = outgoing.add_stream("libx264", rate=original.average_rate)
        encoded.width, encoded.height, encoded.pix_fmt = width, height, "yuv420p"
        encoded.time_base = encoded.codec_context.time_base = original.time_base
        encoded.options = {"crf": "18", "preset": "fast"}
        for name in ("color_range", "colorspace", "color_primaries", "color_trc"):
            setattr(encoded.codec_context, name, getattr(original.codec_context, name))
        count = 0

        def active(frame):
            if frame.pts is None:
                raise ValueError("missing frame timestamp")
            at = float(frame.pts * frame.time_base)
            return matching_boxes(frame.to_ndarray(format="bgr24"), at, samples)

        # Re-check the detected glyph edges in every frame to avoid painting
        # across a scene change or when a moving/disappearing mark has left.
        for selected, group in itertools.groupby(incoming.decode(video=0), active):
            mask = np.zeros((height, width), np.uint8)
            for x1, y1, x2, y2 in selected:
                mask[y1:y2, x1:x2] = 255
            while batch := list(itertools.islice(group, 50)):
                count += len(batch)
                if count > 6000 or (
                    silent.exists() and silent.stat().st_size > MAX_BYTES
                ):
                    raise ValueError("processing limit exceeded")
                arrays = [frame.to_ndarray(format="bgr24") for frame in batch]
                repaired = model(arrays, mask) if selected else arrays
                for src, array in zip(batch, repaired, strict=True):
                    frame = av.VideoFrame.from_ndarray(array, format="bgr24")
                    frame.pts, frame.time_base = src.pts, src.time_base
                    for packet in encoded.encode(frame):
                        outgoing.mux(packet)
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
        "-map_metadata",
        "1",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output),
    )
    evidence = verify(source, output, original_sha)
    output.with_suffix(".json").write_text(json.dumps(evidence))
    silent.unlink()


if __name__ == "__main__":
    main()
