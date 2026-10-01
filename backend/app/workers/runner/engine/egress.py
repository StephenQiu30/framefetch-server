"""Fixed route bindings and bounded IP observations through the same proxy."""

import asyncio
import ipaddress
import json
import time
from dataclasses import dataclass, field, replace
from hashlib import sha256

import httpx
from app.services.provider_types import EgressRoute
from app.workers.runner.provider_registry import ProviderProfile
from app.workers.runner.settings import ProviderEgressSettings

_CACHE_SECONDS = 600
_observations: dict[tuple[str, str], tuple[float, str | None]] = {}


@dataclass(frozen=True, slots=True)
class EgressBinding:
    route: str
    proxy_url: str = field(repr=False)
    revision: str
    egress_class: str
    observed_ip: str | None


def resolve_egress(
    profile: ProviderProfile, *, settings: ProviderEgressSettings | None = None
) -> EgressBinding:
    settings = settings or ProviderEgressSettings()
    # Generic media has no platform declaration: its neutral default is global.
    route = (
        EgressRoute.GLOBAL
        if profile.egress_route is EgressRoute.BY_DOMAIN
        else profile.egress_route
    )
    global_route = route is EgressRoute.GLOBAL
    proxy = (
        settings.runner_global_egress_proxy
        if global_route
        else settings.runner_egress_proxy
    )
    host = (
        settings.egress_global_upstream_host
        if global_route
        else settings.egress_cn_upstream_host
    )
    port = (
        settings.egress_global_upstream_port
        if global_route
        else settings.egress_cn_upstream_port
    )
    egress_class = "residential" if host else "unknown"
    if global_route and not host:
        host, port = (
            settings.egress_fallback_upstream_host,
            settings.egress_fallback_upstream_port,
        )
        egress_class = "datacenter"
    revision = sha256(
        json.dumps(
            [
                route,
                proxy,
                host or "direct",
                port,
                egress_class,
                settings.egress_node_revision,
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    cached = _observations.get((revision, settings.runner_egress_ip_echo_url))
    observed_ip = cached[1] if cached and cached[0] > time.monotonic() else None
    return EgressBinding(str(route), proxy, revision, egress_class, observed_ip)


async def observe_egress(
    binding: EgressBinding, *, settings: ProviderEgressSettings
) -> EgressBinding:
    """Cache success and failure for ten minutes; never follow echo redirects."""
    key = (binding.revision, settings.runner_egress_ip_echo_url)
    cached = _observations.get(key)
    if cached and cached[0] > time.monotonic():
        return replace(binding, observed_ip=cached[1])
    observed = None
    try:
        async with asyncio.timeout(5):
            async with httpx.AsyncClient(
                proxy=binding.proxy_url,
                trust_env=False,
                follow_redirects=False,
                timeout=4,
            ) as client:
                async with client.stream(
                    "GET", settings.runner_egress_ip_echo_url
                ) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=129):
                        body.extend(chunk)
                        if len(body) > 128:
                            raise ValueError("IP echo exceeds limit")
                    address = ipaddress.ip_address(body.decode("ascii").strip())
                    if (
                        not address.is_global
                        or address.is_multicast
                        or "%" in str(address)
                    ):
                        raise ValueError("IP echo is not public")
                    observed = str(address)
    except (httpx.HTTPError, TimeoutError, ValueError, UnicodeError):
        pass
    now = time.monotonic()
    for old_key, (expires, _) in tuple(_observations.items()):
        if expires <= now:
            del _observations[old_key]
    _observations[key] = (now + _CACHE_SECONDS, observed)
    return replace(binding, observed_ip=observed)
