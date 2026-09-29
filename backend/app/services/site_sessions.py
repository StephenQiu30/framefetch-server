"""Site sessions: which login identity a URL needs, keyed by a domain.

Pure session requirements and domain validation; platform declarations live in
the Provider Registry. This module performs no registry lookup or browser I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from ipaddress import ip_address

import tldextract

_HOST = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"
)
# Offline snapshot only: resolution must be deterministic and never fetch at runtime.
_PUBLIC_SUFFIXES = tldextract.TLDExtract(
    cache_dir=None,
    suffix_list_urls=(),
    include_psl_private_domains=True,
)


class SessionEntitlement(StrEnum):
    PUBLIC_ONLY = "public_only"
    ACCOUNT_ENTITLED_FULL_VIDEO = "account_entitled_full_video"


class CookieRequirement(StrEnum):
    ANY = "any"
    ALL = "all"


class HeaderPlugin(StrEnum):
    YUANBAO = "yuanbao"


class InvalidSessionSite(ValueError):
    """The host cannot own a deployment session."""


@dataclass(frozen=True, slots=True)
class SiteSessionPolicy:
    site: str
    provider_key: str | None
    keepalive_url: str
    entitlement: SessionEntitlement = SessionEntitlement.PUBLIC_ONLY
    required_cookie_names: frozenset[str] = frozenset()
    requirement: CookieRequirement = CookieRequirement.ANY
    header_plugin: HeaderPlugin | None = None

    def __post_init__(self) -> None:
        if _HOST.fullmatch(self.site) is None:
            raise ValueError(f"invalid session site: {self.site}")
        if not self.keepalive_url.startswith("https://"):
            raise ValueError(f"session keepalive must use HTTPS: {self.site}")

    def accepts(self, cookie_names: frozenset[str]) -> bool:
        if not cookie_names:
            return False
        if not self.required_cookie_names:
            return True
        if self.requirement is CookieRequirement.ALL:
            return self.required_cookie_names <= cookie_names
        return bool(self.required_cookie_names & cookie_names)


def registrable_site(host: str) -> str:
    """Return the registrable domain that scopes an unknown site's session."""
    normalized = host.strip().lower().rstrip(".")
    try:
        ip_address(normalized.strip("[]"))
    except ValueError:
        pass
    else:
        raise InvalidSessionSite("IP addresses cannot own a session")
    if len(normalized) > 253 or _HOST.fullmatch(normalized) is None:
        raise InvalidSessionSite("session site must be a public DNS name")
    parts = _PUBLIC_SUFFIXES(normalized)
    if not parts.suffix or not parts.domain:
        raise InvalidSessionSite("session site must be under a public suffix")
    return parts.top_domain_under_public_suffix
