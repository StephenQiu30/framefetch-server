from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from app.services.provider_failures import FailurePhase
from app.workers.runner.provider_errors import ProviderFailureContext
from app.workers.runner.youku_artifact import (
    _packet_to_remove,
    normalize_terminal_metadata,
    terminal_nonpicture_metadata,
)

CONTEXT = ProviderFailureContext(
    "youku", "https://v.youku.com/v_show/id_fixture.html", True
)


def _packet(kind: int = 37, body: bytes = b"metadata", length_size: int = 4) -> bytes:
    nal = bytes((6, kind, len(body))) + body + b"\x80"
    return len(nal).to_bytes(length_size, "big") + nal


def _fixture(tmp_path: Path):
    packet = _packet()
    artifact = tmp_path / "artifact.mp4"
    artifact.write_bytes(b"picture-prefix" + packet)
    probe = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "codec_tag_string": "avc1",
                "profile": "High",
                "nal_length_size": "4",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "30.1"},
    }
    tail = {
        "packets": [
            {"pts_time": "29.9", "size": "4", "pos": "0", "flags": "___"},
            {"pts_time": "30", "size": str(len(packet)), "pos": "14", "flags": "___"},
        ]
    }
    return artifact, probe, tail


@pytest.mark.parametrize("length_size", [1, 2, 4])
def test_terminal_nesting_metadata_has_no_picture(length_size):
    assert terminal_nonpicture_metadata(_packet(length_size=length_size), length_size)


@pytest.mark.parametrize(
    "packet",
    [
        b"",
        b"\x00\x00\x00\x20\x06",
        b"\x00" * 4,
        _packet(4),
        _packet(5),
        _packet(137),
        _packet(1),
        _packet(37, b""),
        _packet()[:-1],
        _packet() + b"\x00",
        _packet() + b"\x00\x00\x00\x01\x65",
        _packet(37, b"\x00\x00\x03\x04"),
        b"\x00" * (64 * 1024 + 1),
    ],
)
def test_picture_caption_hdr_unknown_or_malformed_packets_are_preserved(packet):
    assert not terminal_nonpicture_metadata(packet, 4)


def test_proven_terminal_packet_is_selected_by_original_position_and_size(tmp_path):
    artifact, probe, tail = _fixture(tmp_path)
    assert _packet_to_remove(artifact, probe, tail) == (14, len(_packet()))
    # B-frame reorder may put the final metadata timestamp before the last picture.
    tail["packets"][0]["pts_time"] = "30.04"
    assert _packet_to_remove(artifact, probe, tail) == (14, len(_packet()))


@pytest.mark.parametrize(
    "key,value",
    [
        ("codec_name", "hevc"),
        ("codec_tag_string", "encv"),
        ("profile", "Multiview High"),
        ("nal_length_size", "3"),
    ],
)
def test_protected_other_codec_or_multiview_stream_is_not_modified(
    tmp_path, key, value
):
    artifact, probe, tail = _fixture(tmp_path)
    probe["streams"][0][key] = value
    assert _packet_to_remove(artifact, probe, tail) is None


@pytest.mark.parametrize(
    "key,value",
    [
        ("pos", "-1"),
        ("pos", "9999"),
        ("size", "0"),
        ("size", "65537"),
        ("flags", "K__"),
        ("pts_time", "28"),
        ("pts_time", "31"),
        ("pts_time", "nan"),
        ("pts_time", "invalid"),
    ],
)
def test_terminal_packet_requires_safe_bounds_end_time_and_non_key(
    tmp_path, key, value
):
    artifact, probe, tail = _fixture(tmp_path)
    tail["packets"][-1][key] = value
    assert _packet_to_remove(artifact, probe, tail) is None


@pytest.mark.parametrize(
    "tail", [{}, {"packets": []}, {"packets": [None]}, {"packets": "bad"}]
)
def test_incomplete_packet_probe_never_removes_data(tmp_path, tail):
    artifact, probe, _ = _fixture(tmp_path)
    assert _packet_to_remove(artifact, probe, tail) is None


async def test_normalization_copies_media_then_reprobes_and_cleans_output(tmp_path):
    artifact, probe, tail = _fixture(tmp_path)
    commands = AsyncMock()
    commands.probe_terminal_packets.return_value = tail
    normalized = deepcopy(probe)
    normalized["format"]["duration"] = "30.04"
    commands.probe.return_value = normalized

    async def remux(inputs, output, container, cwd, **kwargs):
        assert inputs == (artifact,)
        assert container.value == "mp4"
        assert kwargs["drop_video_packet"] == (14, len(_packet()))
        assert kwargs["include_audio"] is True
        output.write_bytes(b"preserved-picture-and-audio")

    commands.remux.side_effect = remux
    result = await normalize_terminal_metadata(
        artifact, probe, commands, failure_context=CONTEXT
    )
    assert result is normalized
    assert artifact.read_bytes() == b"preserved-picture-and-audio"
    assert not (tmp_path / "youku-terminal-normalized.mp4").exists()
    assert commands.probe.call_args.kwargs["phase"] == FailurePhase.VALIDATE
    assert commands.probe_terminal_packets.call_args.kwargs["start_seconds"] == 28.1


async def test_remux_failure_keeps_original_and_cleans_partial_output(tmp_path):
    artifact, probe, tail = _fixture(tmp_path)
    original = artifact.read_bytes()
    commands = AsyncMock()
    commands.probe_terminal_packets.return_value = tail

    async def fail(inputs, output, *args, **kwargs):
        output.write_bytes(b"partial")
        raise RuntimeError("controlled remux failure")

    commands.remux.side_effect = fail
    with pytest.raises(RuntimeError, match="controlled remux failure"):
        await normalize_terminal_metadata(
            artifact, probe, commands, failure_context=CONTEXT
        )
    assert artifact.read_bytes() == original
    assert not (tmp_path / "youku-terminal-normalized.mp4").exists()
    commands.probe.assert_not_called()


@pytest.mark.parametrize(
    "probe",
    [
        {},
        {"streams": None},
        {"streams": [None]},
        {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "codec_tag_string": "encv",
                }
            ]
        },
    ],
)
async def test_invalid_or_protected_probe_never_starts_normalization(tmp_path, probe):
    commands = AsyncMock()
    result = await normalize_terminal_metadata(
        tmp_path / "artifact.mp4",
        probe,
        commands,
        failure_context=CONTEXT,
    )
    assert result is probe
    commands.probe_terminal_packets.assert_not_called()
