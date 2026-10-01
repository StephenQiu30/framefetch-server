"""Remove only a proven terminal, MVC-nesting SEI-only non-picture packet.

Youku's clear H.264 transport appends this metadata as a video packet. Keeping
it in MP4 makes strict decoders report 'no frame'. Picture packets, embedded SEI,
other standalone SEI and every audio packet are left unchanged.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from typing import Any

from app.services.downloads.rules.enums import Container
from app.services.provider_failures import FailurePhase
from app.workers.runner.commands import MediaCommands
from app.workers.runner.provider_errors import ProviderFailureContext

MAX_METADATA_BYTES = 64 * 1024


def _mvc_nesting_sei(nal: bytes) -> bool:
    if not nal or nal[0] != 6:
        return False
    # Undo RBSP byte stuffing only; this is H.264 syntax, never decryption.
    raw = nal[1:]
    rbsp_buffer = bytearray()
    at = 0
    while at < len(raw):
        if raw[at : at + 3] == b"\x00\x00\x03":
            if at + 3 >= len(raw) or raw[at + 3] > 3:
                return False
            rbsp_buffer.extend(b"\x00\x00")
            at += 3
        else:
            rbsp_buffer.append(raw[at])
            at += 1
    rbsp = bytes(rbsp_buffer)
    at = 0
    messages = 0
    while at < len(rbsp):
        if rbsp[at:] == b"\x80":
            return messages > 0
        values = []
        for _ in range(2):
            value = 0
            while at < len(rbsp) and rbsp[at] == 255:
                value += 255
                at += 1
            if at == len(rbsp):
                return False
            value += rbsp[at]
            at += 1
            values.append(value)
        kind, size = values
        if kind != 37 or size < 1 or at + size >= len(rbsp):
            return False
        at += size
        messages += 1
    return False


def terminal_nonpicture_metadata(packet: bytes, length_size: int) -> bool:
    if not packet or len(packet) > MAX_METADATA_BYTES or length_size not in (1, 2, 4):
        return False
    at = 0
    while at < len(packet):
        if at + length_size > len(packet):
            return False
        size = int.from_bytes(packet[at : at + length_size], "big")
        at += length_size
        if (
            not size
            or at + size > len(packet)
            or not _mvc_nesting_sei(packet[at : at + size])
        ):
            return False
        at += size
    return True


def _packet_to_remove(
    artifact: Path, probe: dict[str, Any], tail: dict[str, Any]
) -> tuple[int, int] | None:
    streams = probe.get("streams")
    if not isinstance(streams, list) or not all(isinstance(x, dict) for x in streams):
        return None
    video: dict[str, Any] = next(
        (x for x in streams if x.get("codec_type") == "video"), {}
    )
    if (
        video.get("codec_name") != "h264"
        or video.get("codec_tag_string") != "avc1"
        or video.get("profile") != "High"
    ):
        return None  # In particular never inspect an encv/protected sample.
    try:
        length_size = int(video["nal_length_size"])
        duration = float(probe["format"]["duration"])
        packets = tail["packets"]
        if (
            not isinstance(packets, list)
            or len(packets) < 2
            or not all(isinstance(x, dict) for x in packets)
        ):
            return None
        last = packets[-1]
        pos, size = int(last["pos"]), int(last["size"])
        pts = float(last["pts_time"])
        if (
            not math.isfinite(pts)
            or not math.isfinite(duration)
            or not duration - 1 <= pts <= duration + 0.1
            or "K" in last["flags"]
            or pos < 0
            or not 0 < size <= MAX_METADATA_BYTES
            or pos + size > artifact.stat().st_size
        ):
            return None
        with artifact.open("rb") as stream:
            stream.seek(pos)
            packet = stream.read(size)
        return (
            (pos, size) if terminal_nonpicture_metadata(packet, length_size) else None
        )
    except (KeyError, TypeError, ValueError, OSError):
        return None


async def normalize_terminal_metadata(
    artifact: Path,
    probe: dict[str, Any],
    commands: MediaCommands,
    *,
    failure_context: ProviderFailureContext,
) -> dict[str, Any]:
    streams = probe.get("streams")
    if not isinstance(streams, list) or not all(isinstance(x, dict) for x in streams):
        return probe
    video: dict[str, Any] = next(
        (x for x in streams if x.get("codec_type") == "video"), {}
    )
    if (
        artifact.suffix != ".mp4"
        or video.get("codec_name") != "h264"
        or video.get("codec_tag_string") != "avc1"
        or video.get("profile") != "High"
    ):
        return probe
    try:
        duration = float(probe["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        return probe
    if not math.isfinite(duration) or duration <= 0:
        return probe
    tail = await commands.probe_terminal_packets(
        artifact,
        artifact.parent,
        start_seconds=max(0, duration - 2),
        failure_context=failure_context,
    )
    remove = await asyncio.to_thread(_packet_to_remove, artifact, probe, tail)
    if remove is None:
        return probe
    output = artifact.with_name("youku-terminal-normalized.mp4")
    try:
        await commands.remux(
            (artifact,),
            output,
            Container.MP4,
            artifact.parent,
            include_audio=any(x.get("codec_type") == "audio" for x in probe["streams"]),
            drop_video_packet=remove,
            failure_context=failure_context,
        )
        await asyncio.to_thread(output.replace, artifact)
        return await commands.probe(
            artifact,
            artifact.parent,
            failure_context=failure_context,
            phase=FailurePhase.VALIDATE,
        )
    finally:
        output.unlink(missing_ok=True)
