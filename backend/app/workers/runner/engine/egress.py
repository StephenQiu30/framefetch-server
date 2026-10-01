"""P0 binding to the existing proxy; residential routing is implemented in R1."""

from dataclasses import dataclass, field
from hashlib import sha256

from app.workers.runner.provider_registry import ProviderProfile
from app.workers.runner.settings import ProviderEgressSettings


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
    proxy = settings.egress_proxy_for(profile.key)
    return EgressBinding(
        route=settings.egress_route_for(profile.key),
        proxy_url=proxy,
        revision=sha256(proxy.encode()).hexdigest(),
        egress_class="unknown",
        observed_ip=None,
    )
