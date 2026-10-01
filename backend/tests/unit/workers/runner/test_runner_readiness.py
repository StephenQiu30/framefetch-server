from __future__ import annotations

from pathlib import Path

import pytest
from api_helpers import settings
from app.workers.runner import readiness
from app.workers.runner.readiness import RunnerReadiness


@pytest.mark.asyncio
async def test_runner_readiness_checks_binaries_workspace_and_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = settings(tmp_path).model_copy(
        update={
            "runner_youtube_pot_base_url": "http://youtube-pot-provider:4416",
        }
    )
    endpoints: list[str] = []

    async def tcp_ready(url: str) -> bool:
        endpoints.append(url)
        return True

    monkeypatch.setattr(readiness, "_tcp_ready", tcp_ready)
    monkeypatch.setattr(readiness, "_runtime_packages_ready", lambda _settings: True)
    probe = RunnerReadiness(configured, binary_exists=lambda binary: binary)

    assert await probe.check() is True
    assert endpoints == [configured.runner_egress_proxy]


@pytest.mark.asyncio
async def test_runner_readiness_fails_when_a_dependency_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(readiness, "_runtime_packages_ready", lambda _settings: True)
    missing_binary = RunnerReadiness(
        settings(tmp_path),
        binary_exists=lambda binary: (
            None if binary == settings(tmp_path).runner_ytdlp_bin else binary
        ),
    )
    missing_workspace = RunnerReadiness(
        settings(tmp_path / "missing"),
        binary_exists=lambda binary: binary,
    )
    monkeypatch.setattr(readiness, "_tcp_ready", _always_ready)

    assert await missing_binary.check() is False
    assert await missing_workspace.check() is False


@pytest.mark.asyncio
async def test_runner_readiness_rejects_runtime_version_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = settings(tmp_path).model_copy(
        update={
            "runner_youtube_pot_base_url": "http://youtube-pot-provider:4416",
        }
    )
    monkeypatch.setattr(readiness, "_tcp_ready", _always_ready)
    monkeypatch.setattr(readiness, "_runtime_packages_ready", lambda _settings: False)
    probe = RunnerReadiness(configured, binary_exists=lambda binary: binary)

    assert await probe.check() is False


def test_runtime_package_probe_accepts_version_drift_but_requires_binaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = settings(tmp_path)
    packages = {
        "yt-dlp": (
            "2026.8.19",
            "https://github.com/yt-dlp/yt-dlp/archive/incorrect.tar.gz",
        ),
        "bgutil-ytdlp-pot-provider": ("1.3.2", None),
    }
    monkeypatch.setattr(readiness, "_package_record", packages.get)

    assert readiness._runtime_packages_ready(configured) is True

    packages["yt-dlp"] = (
        "2026.8.19",
        "https://github.com/yt-dlp/yt-dlp/archive/"
        f"{configured.runner_ytdlp_commit}.tar.gz",
    )

    assert readiness._runtime_packages_ready(configured) is True

    wrong_binary = configured.model_copy(update={"runner_ytdlp_bin": "python"})
    assert readiness._runtime_packages_ready(wrong_binary) is False

    wrong_pot = configured.model_copy(
        update={"runner_youtube_pot_provider_version": "bgutil-http-9.9.9"}
    )
    assert readiness._runtime_packages_ready(wrong_pot) is True


async def _always_ready(_url: str) -> bool:
    return True
