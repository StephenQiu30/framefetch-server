from __future__ import annotations

import inspect
import os
import subprocess
from pathlib import Path

import yaml
from yt_dlp_plugins.extractor.getpot_bgutil_http import BgUtilHTTPPTP

ROOT = Path(__file__).resolve().parents[2]


def test_private_provider_sources_are_excluded_from_docker_build_context() -> None:
    for project in (ROOT, ROOT.parent / "frontend"):
        rules = (project / ".dockerignore").read_text().splitlines()
        for directory in (".provider-sessions", ".provider-secrets"):
            assert f"**/{directory}/" in rules
        assert not any("provider-" in rule and rule.startswith("!") for rule in rules)


def test_pyproject_and_compose_pin_provider_runtime() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text()
    compose = (ROOT.parent / "docker-compose.yml").read_text()
    production_compose = (ROOT.parent / "docker-compose-prod.yml").read_text()
    supervisor = (
        ROOT / "app" / "workers" / "runner" / "youtube-pot-supervisor.mjs"
    ).read_text()

    image = (
        "bgutil-ytdlp-pot-provider:2.0.0@"
        "sha256:ed86b6fdd5e430ddd7c8ce1adb55e1ab54db7c7dbc1bcbf3a82454a85b971164"
    )
    assert '"bgutil-ytdlp-pot-provider==2.0.0"' in pyproject
    assert "51bab8a0116f4d8004c315706d809782607d5847.tar.gz" in pyproject
    assert image in compose
    assert image in production_compose
    assert "youtube-pot-supervisor.mjs" in compose
    assert "youtube-pot-supervisor.mjs" in production_compose
    assert "const FAILURE_THRESHOLD = 3" in supervisor
    assert "expectedVersion" not in supervisor
    assert 'stdio: ["ignore", "ignore", "ignore"]' in supervisor
    assert 'stdio: "inherit"' not in supervisor
    assert "delete childEnvironment.RUNNER_EGRESS_PROXY" in supervisor
    assert "delete childEnvironment.RUNNER_PROVIDER_EGRESS_PROXIES" in supervisor
    assert "const MAX_RESTART_DELAY_MS = 30_000" in supervisor
    assert "restartDelayMs = RESTART_DELAY_MS" in supervisor


def test_youtube_sidecar_and_runners_can_only_egress_through_a_gateway() -> None:
    for filename in ("docker-compose.yml", "docker-compose-prod.yml"):
        document = yaml.safe_load((ROOT.parent / filename).read_text())
        services = document["services"]
        networks = document["networks"]
        sidecar = services["youtube-pot-provider"]
        assert sidecar["healthcheck"]["test"] == [
            "CMD",
            "/usr/local/bin/node",
            "/opt/video/youtube-pot-supervisor.mjs",
            "--check-health",
        ]
        assert (
            services["session-runner"]["depends_on"]["youtube-pot-provider"][
                "condition"
            ]
            == "service_healthy"
        )

        assert set(sidecar["networks"]) == {"youtube_pot_net"}
        assert networks["youtube_pot_net"]["internal"] is True
        assert networks["runner_egress_net"]["internal"] is True
        assert not (networks["proxy_uplink_net"] or {}).get("internal", False)
        assert "youtube_pot_net" in services["session-runner"]["networks"]
        assert "youtube_pot_net" in services["egress-proxy"]["networks"]
        assert "runner_egress_net" in services["egress-proxy"]["networks"]
        assert "proxy_uplink_net" in services["egress-proxy"]["networks"]
        assert "youtube_pot_net" not in services["api"]["networks"]
        assert "proxy_uplink_net" not in services["api"]["networks"]
        assert "proxy_uplink_net" not in services["session-runner"]["networks"]
        assert "runner_egress_net" not in sidecar["networks"]
        assert "proxy_uplink_net" not in sidecar["networks"]
        assert {
            name
            for name, service in services.items()
            if "proxy_uplink_net" in (service.get("networks") or [])
        } == {"egress-proxy"}
        assert sidecar["read_only"] is True
        assert sidecar["tmpfs"] == ["/tmp:rw,noexec,nosuid,size=16m"]
        assert (
            sidecar["environment"]["RUNNER_EGRESS_PROXY"]
            == (services["session-runner"]["environment"]["RUNNER_EGRESS_PROXY"])
        )
        assert (
            sidecar["environment"]["RUNNER_PROVIDER_EGRESS_PROXIES"]
            == (
                services["session-runner"]["environment"][
                    "RUNNER_PROVIDER_EGRESS_PROXIES"
                ]
            )
        )


def test_pinned_bgutil_forwards_the_runner_proxy_without_proxying_internal_rpc() -> (
    None
):
    source = inspect.getsource(BgUtilHTTPPTP._real_request_pot)

    assert "'proxy': request.request_proxy" in source
    assert "proxies={'all': None}" in source


def test_youtube_sidecar_accepts_the_same_provider_override_as_runner() -> None:
    completed = _supervisor_config_check(
        '{"youtube":"http://youtube-egress-gateway:3128"}'
    )

    assert completed.returncode == 0
    assert completed.stdout == ""
    assert completed.stderr == ""


def test_youtube_sidecar_rejects_invalid_egress_without_disclosing_it() -> None:
    sensitive = "do-not-disclose.invalid"
    for overrides in (
        "",
        f'{{"youtube":"http://user:secret@{sensitive}:3128"}}',
        f'{{"youtube":"http://{sensitive}:3128/path"}}',
        f'{{"youtube":"http://{sensitive}:3128/"',
        f'["http://{sensitive}:3128"]',
        f'{{"YouTube":"http://{sensitive}:3128"}}',
    ):
        completed = _supervisor_config_check(overrides)
        output = f"{completed.stdout}\n{completed.stderr}"

        assert completed.returncode != 0
        assert sensitive not in output
        assert "secret" not in output

    invalid_fallback = f"http://user:secret@{sensitive}:3128"
    completed = _supervisor_config_check("{}", fallback=invalid_fallback)
    output = f"{completed.stdout}\n{completed.stderr}"

    assert completed.returncode != 0
    assert sensitive not in output
    assert "secret" not in output


def _supervisor_config_check(
    overrides: str,
    *,
    fallback: str = "http://egress-proxy:3128",
) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "RUNNER_EGRESS_PROXY": fallback,
        "RUNNER_PROVIDER_EGRESS_PROXIES": overrides,
    }
    return subprocess.run(
        [
            "node",
            str(ROOT / "app" / "workers" / "runner" / "youtube-pot-supervisor.mjs"),
            "--check-config",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_compose_inspection_timeout_matches_the_120_second_design_limit() -> None:
    root = Path(__file__).resolve().parents[3]
    for filename in ("docker-compose.yml", "docker-compose-prod.yml"):
        services = yaml.safe_load((root / filename).read_text())["services"]
        for role in ("api", "worker"):
            assert services[role]["environment"]["INSPECT_TIMEOUT_SECONDS"] == (
                "${INSPECT_TIMEOUT_SECONDS:-120}"
            )
    assert "INSPECT_TIMEOUT_SECONDS=120" in (root / ".env.example").read_text()
