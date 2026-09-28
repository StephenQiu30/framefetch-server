from __future__ import annotations

from pathlib import Path

import pytest
from app.workers.runner import settings as runner_settings
from app.workers.runner.settings import (
    RunnerSettings,
    egress_affinity_id,
    get_runner_settings,
)
from pydantic import ValidationError

SECRET = "runner-shared-secret-material-at-least-32-bytes"


def test_proxy_and_hmac_secret_are_required_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        RunnerSettings(
            runner_hmac_secret=SECRET,
            runner_workspace_root=tmp_path,
        )


def test_loads_minimal_runner_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RUNNER_HMAC_SECRET", SECRET)
    monkeypatch.setenv("RUNNER_EGRESS_PROXY", "http://egress-proxy:3128")
    monkeypatch.setenv("RUNNER_WORKSPACE_ROOT", str(tmp_path))

    settings = RunnerSettings()

    assert settings.hmac_secret_bytes == SECRET.encode()
    assert settings.runner_egress_proxy == "http://egress-proxy:3128"
    assert settings.runner_provider_egress_proxies == {}
    assert settings.runner_youtube_pot_provider_version == "bgutil-http-1.3.2"
    assert settings.runner_workspace_root == tmp_path.resolve()
    assert settings.runner_inspect_timeout_seconds == 120
    assert settings.runner_download_timeout_seconds == 7_200
    assert settings.runner_max_duration_seconds == 86_400
    assert settings.runner_max_output_bytes == 20 * 1024**3
    assert settings.runner_max_workspace_bytes == 40 * 1024**3


def test_local_runner_loads_the_repository_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    environment = tmp_path / ".env"
    environment.write_text(
        "RUNNER_HMAC_SECRET=" + SECRET + "\n"
        "RUNNER_EGRESS_PROXY=http://127.0.0.1:13128\n"
        "RUNNER_WORKSPACE_ROOT=" + str(tmp_path / "work") + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runner_settings, "REPOSITORY_ROOT", tmp_path)

    settings = get_runner_settings()

    assert settings.runner_egress_proxy == "http://127.0.0.1:13128"
    assert settings.runner_workspace_root == (tmp_path / "work").resolve()


def test_loads_credential_free_provider_proxy_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RUNNER_HMAC_SECRET", SECRET)
    monkeypatch.setenv("RUNNER_EGRESS_PROXY", "http://egress-proxy:3128")
    monkeypatch.setenv(
        "RUNNER_PROVIDER_EGRESS_PROXIES",
        '{"youtube":"http://youtube-egress:3128"}',
    )
    monkeypatch.setenv("RUNNER_WORKSPACE_ROOT", str(tmp_path))

    settings = RunnerSettings()

    assert settings.egress_proxy_for("youtube") == "http://youtube-egress:3128"
    assert settings.egress_proxy_for("bilibili") == "http://egress-proxy:3128"
    assert settings.egress_affinity_for("youtube") == egress_affinity_id(
        "provider:youtube", "http://youtube-egress:3128"
    )
    assert settings.egress_affinity_for("bilibili") == egress_affinity_id(
        "default", "http://egress-proxy:3128"
    )


def test_egress_affinity_changes_with_the_route_without_exposing_it() -> None:
    first = egress_affinity_id("provider:youtube", "http://egress-a:3128")
    second = egress_affinity_id("provider:youtube", "http://egress-b:3128")

    assert first != second
    assert first.startswith("provider:youtube:")
    assert "egress-a" not in first


def test_anonymous_runner_can_use_service_managed_youtube_pot(
    tmp_path: Path,
) -> None:
    settings = RunnerSettings(
        runner_hmac_secret=SECRET,
        runner_egress_proxy="http://egress-proxy:3128",
        runner_workspace_root=tmp_path,
        runner_youtube_pot_base_url="http://youtube-pot-provider:4416",
    )

    assert settings.runner_youtube_pot_base_url.endswith(":4416")


def test_runner_uses_the_same_exact_peertube_instance_allowlist(
    tmp_path: Path,
) -> None:
    settings = RunnerSettings(
        runner_hmac_secret=SECRET,
        runner_egress_proxy="http://egress-proxy:3128",
        runner_workspace_root=tmp_path,
        peertube_allowed_instances=frozenset({"VIDEO.EXAMPLE.COM"}),
    )

    assert settings.peertube_allowed_instances == frozenset({"video.example.com"})
    with pytest.raises(ValidationError, match="invalid host"):
        RunnerSettings(
            runner_hmac_secret=SECRET,
            runner_egress_proxy="http://egress-proxy:3128",
            runner_workspace_root=tmp_path,
            peertube_allowed_instances=frozenset({"*.example.com"}),
        )


@pytest.mark.parametrize(
    "proxy",
    [
        "socks5://egress-proxy:1080",
        "http://user:password@egress-proxy:3128",
        "http:///missing-host",
        "http://egress-proxy:3128/path",
    ],
)
def test_rejects_unsafe_proxy_configuration(proxy: str, tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        RunnerSettings(
            runner_hmac_secret=SECRET,
            runner_egress_proxy=proxy,
            runner_workspace_root=tmp_path,
        )


def test_rejects_provider_proxy_credentials(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        RunnerSettings(
            runner_hmac_secret=SECRET,
            runner_egress_proxy="http://egress-proxy:3128",
            runner_provider_egress_proxies={
                "youtube": "http://user:secret@youtube-egress:3128"
            },
            runner_workspace_root=tmp_path,
        )


def test_rejects_provider_proxy_with_surrounding_whitespace(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError):
        RunnerSettings(
            runner_hmac_secret=SECRET,
            runner_egress_proxy="http://egress-proxy:3128",
            runner_provider_egress_proxies={"youtube": " http://youtube-egress:3128"},
            runner_workspace_root=tmp_path,
        )
