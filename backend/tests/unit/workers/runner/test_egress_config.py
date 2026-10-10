from pathlib import Path

from tests.compose import load_compose as load_compose_file

BACKEND_ROOT = Path(__file__).resolve().parents[4]
CONFIG = BACKEND_ROOT / "egress" / "squid.conf"
CONFIG_ROOT = CONFIG.parent
REPOSITORY_ROOT = BACKEND_ROOT.parent
SQUID_IMAGE = (
    "ubuntu/squid:6.6-24.04_edge@"
    "sha256:8a3baed477e2c282ab8aa5edad442f69873246964f225c5c2ae8364b6610963c"
)
EXPECTED_TMPFS = ["/tmp:rw,noexec,nosuid,size=16m,mode=1777"]


def load_compose(filename: str) -> dict:
    return load_compose_file(REPOSITORY_ROOT / filename)


def test_bilibili_tls_media_port_is_scoped_to_its_cdn() -> None:
    config = CONFIG.read_text(encoding="utf-8")

    assert "acl safe_ports port 4483" in config
    assert "acl safe_ports port 8082" in config
    assert "acl ssl_ports port 4483" in config
    assert "acl ssl_ports port 8082" in config
    assert (
        "acl bilibili_media dstdom_regex -i "
        "\\.(bilivideo\\.(cn|com)|mountaintoys\\.cn)$" in config
    )
    assert "http_access deny bilibili_media_port !bilibili_media" in config
    assert (
        "http_access allow docker_clients bilibili_media_port "
        "bilibili_media docker_desktop_synthetic_dns" in config
    )
    assert "acl docker_desktop_web_port port 80 443" in config
    assert (
        "http_access allow docker_clients docker_desktop_web_port "
        "docker_desktop_synthetic_dns" in config
    )

    scoped_deny = config.index("http_access deny bilibili_media_port !bilibili_media")
    public_allow = config.index("http_access allow docker_clients bilibili_media_port")
    assert scoped_deny < public_allow


def test_destination_policy_allows_configured_synthetic_dns_ranges() -> None:
    policy = (CONFIG_ROOT / "blocked-destinations.conf").read_text(encoding="utf-8")
    config = CONFIG.read_text(encoding="utf-8")

    # The local Firecrawl profile relies on these synthetic answers; the egress
    # proxy must allow the exact ranges while keeping other private ranges blocked.
    assert "acl docker_desktop_synthetic_dns dst 198.18.0.0/15" in policy
    assert "acl blocked_destination dst 198.18.0.0/15" not in policy
    assert "acl docker_desktop_synthetic_dns dst fdfe:dcba:9876::/48" in policy
    assert "acl blocked_destination dst fdfe:dcba:9876::/48" not in policy
    assert "acl docker_desktop_synthetic_dns dst 2001:2::/48" in policy
    assert "acl blocked_destination dst 2001:2::/48" not in policy
    for blocked in (
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "fc00::/7",
    ):
        assert f"acl blocked_destination dst {blocked}" in policy
    assert config.index("http_access deny ip_literal_url") < config.index(
        "http_access allow docker_clients docker_desktop_web_port "
        "docker_desktop_synthetic_dns"
    )
    assert config.index(
        "http_access allow docker_clients docker_desktop_web_port "
        "docker_desktop_synthetic_dns"
    ) < config.index("http_access deny blocked_destination")
    assert not (CONFIG_ROOT / "blocked-destinations-docker-desktop.conf").exists()


def test_compose_mounts_single_destination_policy() -> None:
    variable = "EGRESS_DESTINATION_POLICY_FILE"
    mount = "./backend/egress:/etc/squid/policy:ro"
    text = str(load_compose("docker-compose.yml"))
    assert variable not in text
    assert mount in text

    example = (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8")
    assert variable not in example


def test_egress_proxy_uses_pinned_squid_without_a_go_build_surface() -> None:
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert not (BACKEND_ROOT / "egress-proxy").exists()
    assert "golang" not in dockerfile
    assert "smokescreen" not in dockerfile
    assert "squid" not in dockerfile

    proxy = load_compose("docker-compose.yml")["services"]["egress-proxy"]
    assert proxy["image"] == SQUID_IMAGE
    assert "build" not in proxy
    assert proxy["entrypoint"] == ["/bin/sh", "/etc/squid/policy/start.sh"]
    assert proxy["tmpfs"] == EXPECTED_TMPFS
    # A directory mount follows files replaced by git or editors; a
    # single-file bind mount would keep serving the old inode on Linux.
    assert proxy["volumes"] == ["./backend/egress:/etc/squid/policy:ro"]
    kind, script = proxy["healthcheck"]["test"]
    assert kind == "CMD-SHELL"
    assert script.endswith("squid -k check -f /etc/squid/policy/squid.conf")


def test_egress_proxy_reloads_changed_policy_only_after_it_parses() -> None:
    # `compose up` leaves this container running when only a mounted policy
    # file changes; a stale policy silently blocks newly allowed media hosts.
    _, script = load_compose("docker-compose.yml")["services"]["egress-proxy"][
        "healthcheck"
    ]["test"]
    assert "find /etc/squid/policy -name '*.conf' -newer" in script
    parse = script.index("squid -k parse -f /etc/squid/policy/squid.conf")
    reload = script.index("squid -k reconfigure -f /etc/squid/policy/squid.conf")
    commit = script.index('mv "$$m.next" "$$m"')
    assert parse < reload < commit
    assert "|| exit 1; fi;" in script


def test_douyin_cold_media_port_remains_domain_scoped() -> None:
    config = CONFIG.read_text(encoding="utf-8")
    assert "acl safe_ports port 8889" in config
    assert "acl ssl_ports port 8889" in config
    assert "acl douyin_cold_media dstdomain .wmzfylgdsz.com" in config
    deny = config.index("http_access deny douyin_cold_media_port !douyin_cold_media")
    allow = config.index(
        "http_access allow docker_clients douyin_cold_media_port "
        "douyin_cold_media docker_desktop_synthetic_dns"
    )
    assert deny < allow
    assert config.index("http_access deny ip_literal_url") < allow
    assert config.index("http_access deny blocked_name") < allow
    assert "http_access deny blocked_destination" in config


def test_cookie_source_exception_is_exact_direct_and_does_not_log_secrets():
    config = CONFIG.read_text()
    allow = (
        "http_access allow docker_clients cookie_source_host cookie_source_port "
        "cookie_source_method cookie_source_path"
    )
    assert "acl cookie_source_host dstdomain host.docker.internal" in config
    assert "acl cookie_source_port port 19101" in config
    assert "acl cookie_source_method method POST" in config
    path_acl = "acl cookie_source_path urlpath_regex ^/(cookies|yuanbao-parse)$"
    assert path_acl in config
    import re

    pattern = path_acl.rsplit(" ", 1)[1]
    assert all(re.fullmatch(pattern, path) for path in ("/cookies", "/yuanbao-parse"))
    assert not any(
        re.fullmatch(pattern, path)
        for path in (
            "/",
            "/extension",
            "/cookies/",
            "/yuanbao-parse/",
            "/yuanbao-parse?url=x",
        )
    )
    assert config.index("http_access deny !docker_clients") < config.index(allow)
    for deny in (
        "http_access deny !safe_ports",
        "http_access deny blocked_name",
        "http_access deny blocked_destination",
    ):
        assert config.index(allow) < config.index(deny)
    assert config.index("http_access deny ip_literal_url") < config.index(allow)
    assert config.index(allow) < config.index("http_access deny cookie_source_host")
    assert "always_direct allow cookie_source_host cookie_source_port" in config
    assert "access_log none" in config and "cache_store_log none" in config


def test_identity_token_is_only_in_session_runner_environment():
    services = load_compose("docker-compose.yml")["services"]
    holders = [
        name
        for name, service in services.items()
        if service.get("env_file")
        == [{"path": "./.local-runtime/identity/runner.env", "required": False}]
    ]
    assert holders == ["session-runner"]
    assert all(
        "COOKIE_SOURCE_TOKEN" not in service.get("environment", {})
        for service in services.values()
    )
    assert services["session-runner"]["environment"]["COOKIE_SOURCE_PORT"] == "19101"


def render_routes(tmp_path, *, ipv4=None, **environment):
    import os
    import subprocess

    executable = tmp_path / "squid"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    resolver = tmp_path / "getent"
    resolver.write_text(
        "#!/bin/sh\n"
        + (
            f'printf "%s STREAM\\n%s DGRAM\\n" "{ipv4}" "{ipv4}"\n'
            if ipv4
            else "exit 2\n"
        )
    )
    resolver.chmod(0o700)
    routes = tmp_path / "routes.conf"
    hosts = tmp_path / "hosts.input"
    hosts.write_text(
        "127.0.0.1 localhost\n192.0.2.1 host.docker.internal\n"
        "fdc4::254 host.docker.internal gateway-alias\n198.51.100.1 unrelated-host\n"
    )
    script = (
        (CONFIG_ROOT / "start.sh")
        .read_text()
        .replace("/tmp/egress-routes.conf", str(routes))
        .replace("/etc/hosts", str(hosts))
        .replace("/tmp/identity-hosts", str(tmp_path / "identity-hosts"))
    )
    result = subprocess.run(
        ["/bin/sh"],
        input=script,
        text=True,
        capture_output=True,
        env={"PATH": str(tmp_path) + ":" + os.defpath, **environment},
    )
    return result, routes.read_text() if routes.exists() else ""


def test_identity_direct_host_prefers_ipv4_without_changing_other_hosts(tmp_path):
    result, _ = render_routes(tmp_path, ipv4="192.0.2.25")
    assert result.returncode == 0, result.stderr
    hosts = (tmp_path / "identity-hosts").read_text()
    assert hosts.count("host.docker.internal") == 1
    assert "192.0.2.25 host.docker.internal" in hosts
    assert "fdc4::254 gateway-alias" in hosts
    assert "127.0.0.1 localhost" in hosts
    assert "198.51.100.1 unrelated-host" in hosts
    assert "hosts_file /tmp/identity-hosts" in CONFIG.read_text()


def test_identity_direct_host_preserves_ipv6_only_resolution(tmp_path):
    result, _ = render_routes(tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "identity-hosts").read_bytes() == (
        tmp_path / "hosts.input"
    ).read_bytes()


def test_squid_routes_use_distinct_configured_parents(tmp_path):
    result, routes = render_routes(
        tmp_path,
        EGRESS_CN_UPSTREAM_HOST="host.docker.internal",
        EGRESS_CN_UPSTREAM_PORT="17897",
        EGRESS_GLOBAL_UPSTREAM_HOST="host.docker.internal",
        EGRESS_GLOBAL_UPSTREAM_PORT="17898",
    )
    assert result.returncode == 0, result.stderr
    assert "cache_peer host.docker.internal parent 17897 0" in routes
    assert "cache_peer host.docker.internal parent 17898 0" in routes
    for name in ("cn", "global"):
        route = name + "_residential"
        assert f"cache_peer_access {name}_parent allow {route}" in routes
        assert f"cache_peer_access {name}_parent deny all" in routes
        assert f"never_direct allow {route}" in routes
    assert "always_direct" not in routes
    config = CONFIG.read_text()
    assert "http_port 3128 name=cn_residential" in config
    assert "http_port 3129 name=global_residential" in config


def test_squid_unconfigured_residential_keeps_domestic_and_falls_back_global(tmp_path):
    result, routes = render_routes(
        tmp_path,
        EGRESS_FALLBACK_UPSTREAM_HOST="fallback-host",
        EGRESS_FALLBACK_UPSTREAM_PORT="7897",
    )
    assert result.returncode == 0
    assert "always_direct allow cn_residential" in routes
    assert "cache_peer fallback-host parent 7897 0" in routes
    assert "never_direct allow global_residential" in routes
    assert "cn_parent" not in routes


def test_squid_configuration_rejects_injected_directives_and_invalid_ports(tmp_path):
    for environment in (
        {"EGRESS_GLOBAL_UPSTREAM_HOST": "host\nhttp_access allow all"},
        {"EGRESS_CN_UPSTREAM_PORT": "0"},
        {"EGRESS_GLOBAL_UPSTREAM_PORT": "65536", "EGRESS_GLOBAL_UPSTREAM_HOST": "host"},
        {"EGRESS_CN_UPSTREAM_PORT": "3128; echo injected"},
    ):
        result, routes = render_routes(tmp_path, **environment)
        assert result.returncode != 0
        assert not routes


def test_compose_runner_and_squid_share_upstream_configuration():
    services = load_compose("docker-compose.yml")["services"]
    runner = services["session-runner"]["environment"]
    assert runner["RUNNER_CN_EGRESS_IP_ECHO_URL"] == (
        "${RUNNER_CN_EGRESS_IP_ECHO_URL:-https://ip.3322.net}"
    )
    assert runner["RUNNER_GLOBAL_EGRESS_IP_ECHO_URL"] == (
        "${RUNNER_GLOBAL_EGRESS_IP_ECHO_URL:-https://ipinfo.io/ip}"
    )
    assert "RUNNER_EGRESS_IP_ECHO_URL" not in runner
    proxy = services["egress-proxy"]["environment"]
    for name, value in proxy.items():
        assert runner[name] == value
    assert runner["RUNNER_GLOBAL_EGRESS_PROXY"] == "http://egress-proxy:3129"
    assert (
        services["youtube-pot-provider"]["environment"]["RUNNER_EGRESS_PROXY"]
        == runner["RUNNER_GLOBAL_EGRESS_PROXY"]
    )


def test_squid_peer_prefers_ipv4_when_host_also_has_unroutable_ipv6(tmp_path):
    result, routes = render_routes(
        tmp_path,
        ipv4="192.0.2.42",
        EGRESS_CN_UPSTREAM_HOST="host.docker.internal",
        EGRESS_CN_UPSTREAM_PORT="17897",
        EGRESS_GLOBAL_UPSTREAM_HOST="host.docker.internal",
        EGRESS_GLOBAL_UPSTREAM_PORT="17898",
    )
    assert result.returncode == 0, result.stderr
    assert "cache_peer 192.0.2.42 parent 17897 0" in routes
    assert "cache_peer 192.0.2.42 parent 17898 0" in routes
    assert "cache_peer host.docker.internal" not in routes
