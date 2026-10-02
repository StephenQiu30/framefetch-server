from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from app.integrations.imports.video import (
    VideoProbeResult,
    VideoProbeStream,
    VideoVerificationError,
    VideoVerificationSettings,
    verify_video,
)
from app.services.imports.rules.enums import ImportErrorCode


def box(kind: bytes, payload: bytes = b"") -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


def self_contained_dref() -> bytes:
    url = box(b"url ", b"\x00\x00\x00\x01")
    return box(b"dref", b"\x00\x00\x00\x00" + (1).to_bytes(4, "big") + url)


def mp4_bytes(*, external_reference: bool = False) -> bytes:
    ftyp = box(b"ftyp", b"isom" + b"\x00\x00\x02\x00" + b"isommp42")
    if external_reference:
        url = box(b"url ", b"\x00\x00\x00\x00https://example.invalid/video.mp4")
        dref = box(b"dref", b"\x00\x00\x00\x00" + (1).to_bytes(4, "big") + url)
    else:
        dref = self_contained_dref()
    moov = box(b"moov", box(b"trak", box(b"mdia", box(b"minf", box(b"dinf", dref)))))
    return ftyp + moov + box(b"mdat", b"video-bytes")


class FakeProbe:
    def __init__(self, result: VideoProbeResult) -> None:
        self.result = result
        self.paths: list[Path] = []

    async def probe(
        self, path: Path, settings: VideoVerificationSettings
    ) -> VideoProbeResult:
        self.paths.append(path)
        return self.result


def valid_probe(*, audio: bool = False) -> VideoProbeResult:
    streams = [VideoProbeStream("video", "h264", 1920, 1080)]
    if audio:
        streams.append(VideoProbeStream("audio", "aac"))
    return VideoProbeResult(frozenset({"mov", "mp4"}), 12.5, tuple(streams))


def settings(tmp_path: Path) -> VideoVerificationSettings:
    return VideoVerificationSettings(
        ffprobe_binary=Path("ffprobe"),
        ffprobe_timeout_seconds=5,
        max_probe_output_bytes=64 * 1024,
        max_size_bytes=1024 * 1024,
        max_duration_seconds=60,
    )


async def verified(
    tmp_path: Path,
    *,
    content: bytes | None = None,
    probe_result: VideoProbeResult | None = None,
):
    workspace = tmp_path / "import_1"
    workspace.mkdir()
    path = workspace / "video.mp4"
    payload = mp4_bytes() if content is None else content
    path.write_bytes(payload)
    probe = FakeProbe(probe_result or valid_probe())
    result = await verify_video(
        path,
        workspace_root=tmp_path,
        declared_size_bytes=len(payload),
        declared_sha256=hashlib.sha256(payload).hexdigest(),
        settings=settings(tmp_path),
        probe=probe,
    )
    return result, path, probe


async def test_accepts_self_contained_silent_mp4_and_returns_bounded_metadata(
    tmp_path: Path,
) -> None:
    result, path, probe = await verified(tmp_path)

    assert result.path == path.resolve()
    assert result.duration_ms == 12_500
    assert result.video_streams == 1
    assert result.audio_streams == 0
    assert result.codecs == ("h264",)
    assert result.media_metadata == {
        "audio_streams": 0,
        "codecs": ["h264"],
        "height": 1080,
        "video_streams": 1,
        "width": 1920,
    }
    assert probe.paths == [path.resolve()]


@pytest.mark.parametrize(
    ("declared_size_delta", "digest", "expected"),
    (
        (1, None, ImportErrorCode.SIZE_MISMATCH),
        (0, "0" * 64, ImportErrorCode.SHA256_MISMATCH),
    ),
)
async def test_recomputes_size_and_sha256_before_probe(
    tmp_path: Path,
    declared_size_delta: int,
    digest: str | None,
    expected: ImportErrorCode,
) -> None:
    workspace = tmp_path / "import_1"
    workspace.mkdir()
    path = workspace / "looks-like.mp4"
    payload = mp4_bytes()
    path.write_bytes(payload)
    probe = FakeProbe(valid_probe())

    with pytest.raises(VideoVerificationError) as caught:
        await verify_video(
            path,
            workspace_root=tmp_path,
            declared_size_bytes=len(payload) + declared_size_delta,
            declared_sha256=digest or hashlib.sha256(payload).hexdigest(),
            settings=settings(tmp_path),
            probe=probe,
        )

    assert caught.value.code is expected
    assert probe.paths == []


@pytest.mark.parametrize(
    "payload",
    (
        b"not-an-mp4",
        box(b"ftyp", b"qt  " + b"\x00\x00\x00\x00" + b"qt  ")
        + box(b"moov")
        + box(b"mdat", b"x"),
        mp4_bytes()[:-2],
    ),
)
async def test_rejects_fake_extension_non_mp4_brand_and_corrupt_boxes(
    tmp_path: Path, payload: bytes
) -> None:
    with pytest.raises(VideoVerificationError) as caught:
        await verified(tmp_path, content=payload)

    assert caught.value.code is ImportErrorCode.VIDEO_INVALID


async def test_rejects_external_bmff_data_reference_before_ffprobe(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "import_1"
    workspace.mkdir()
    path = workspace / "video.mp4"
    payload = mp4_bytes(external_reference=True)
    path.write_bytes(payload)
    probe = FakeProbe(valid_probe())

    with pytest.raises(VideoVerificationError) as caught:
        await verify_video(
            path,
            workspace_root=tmp_path,
            declared_size_bytes=len(payload),
            declared_sha256=hashlib.sha256(payload).hexdigest(),
            settings=settings(tmp_path),
            probe=probe,
        )

    assert caught.value.code is ImportErrorCode.VIDEO_INVALID
    assert probe.paths == []


@pytest.mark.parametrize(
    "protected_box", (b"pssh", b"encv", b"enca", b"sinf", b"schm", b"tenc")
)
async def test_rejects_protected_bmff_boxes_before_ffprobe(
    tmp_path: Path, protected_box: bytes
) -> None:
    ftyp = box(b"ftyp", b"isom" + b"\x00\x00\x02\x00" + b"isommp42")
    payload = ftyp + box(b"moov", box(protected_box)) + box(b"mdat", b"video")

    with pytest.raises(VideoVerificationError) as caught:
        await verified(tmp_path, content=payload)

    assert caught.value.code is ImportErrorCode.VIDEO_INVALID


@pytest.mark.parametrize(
    "probe_result",
    (
        VideoProbeResult(
            frozenset({"mov"}), 1, (VideoProbeStream("video", "h264", 1, 1),)
        ),
        VideoProbeResult(
            frozenset({"mp4"}), 0, (VideoProbeStream("video", "h264", 1, 1),)
        ),
        VideoProbeResult(
            frozenset({"mp4"}), 61, (VideoProbeStream("video", "h264", 1, 1),)
        ),
        VideoProbeResult(frozenset({"mp4"}), 1, (VideoProbeStream("audio", "aac"),)),
        VideoProbeResult(
            frozenset({"mp4"}), 1, (VideoProbeStream("video", "unknown", 1, 1),)
        ),
        VideoProbeResult(
            frozenset({"mp4"}), 1, (VideoProbeStream("video", "h264", 9000, 1),)
        ),
        VideoProbeResult(
            frozenset({"mp4"}),
            1,
            (
                VideoProbeStream("video", "h264", 1, 1),
                VideoProbeStream("data", "bin_data"),
            ),
        ),
    ),
)
async def test_rejects_unsafe_or_out_of_policy_probe_metadata(
    tmp_path: Path, probe_result: VideoProbeResult
) -> None:
    with pytest.raises(VideoVerificationError) as caught:
        await verified(tmp_path, probe_result=probe_result)

    assert caught.value.code is ImportErrorCode.VIDEO_INVALID


async def test_rejects_path_outside_private_workspace(tmp_path: Path) -> None:
    workspace_root = tmp_path / "work"
    workspace_root.mkdir()
    path = tmp_path / "outside.mp4"
    payload = mp4_bytes()
    path.write_bytes(payload)

    with pytest.raises(VideoVerificationError) as caught:
        await verify_video(
            path,
            workspace_root=workspace_root,
            declared_size_bytes=len(payload),
            declared_sha256=hashlib.sha256(payload).hexdigest(),
            settings=replace(settings(tmp_path), max_size_bytes=len(payload)),
            probe=FakeProbe(valid_probe()),
        )

    assert caught.value.code is ImportErrorCode.VIDEO_INVALID
