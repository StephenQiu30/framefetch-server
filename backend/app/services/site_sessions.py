"""Site sessions: which login identity a URL needs, keyed by a domain.

The identity is read live from the operator's Chrome for each operation. Known
providers declare their key and session behaviour here; any other site is keyed
by its registrable domain under the bundled Public Suffix List.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from ipaddress import ip_address

import tldextract

from app.services.provider_types import ProviderKey

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
    provider_key: ProviderKey | None
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


_KNOWN_POLICIES = {
    policy.provider_key: policy
    for policy in (
        SiteSessionPolicy(
            "youtube.com",
            ProviderKey.YOUTUBE,
            "https://www.youtube.com/feed/you",
            required_cookie_names=frozenset(
                {
                    "SID",
                    "HSID",
                    "SSID",
                    "APISID",
                    "SAPISID",
                    "__Secure-1PSID",
                    "__Secure-3PSID",
                }
            ),
        ),
        SiteSessionPolicy(
            "douyin.com",
            ProviderKey.DOUYIN,
            "https://www.douyin.com/",
            # ``ttwid`` is issued to every visitor, so it proves nothing.
            required_cookie_names=frozenset({"sessionid", "sessionid_ss", "sid_tt"}),
        ),
        SiteSessionPolicy(
            "xiaohongshu.com",
            ProviderKey.XIAOHONGSHU,
            "https://www.xiaohongshu.com/explore",
            required_cookie_names=frozenset({"web_session"}),
        ),
        SiteSessionPolicy(
            "x.com",
            ProviderKey.X,
            "https://x.com/home",
            required_cookie_names=frozenset({"auth_token", "ct0"}),
            requirement=CookieRequirement.ALL,
        ),
        SiteSessionPolicy(
            "instagram.com",
            ProviderKey.INSTAGRAM,
            "https://www.instagram.com/",
            required_cookie_names=frozenset({"sessionid"}),
        ),
        SiteSessionPolicy(
            "facebook.com",
            ProviderKey.FACEBOOK,
            "https://www.facebook.com/",
            required_cookie_names=frozenset({"c_user", "xs"}),
            requirement=CookieRequirement.ALL,
        ),
        SiteSessionPolicy(
            "reddit.com",
            ProviderKey.REDDIT,
            "https://www.reddit.com/",
            # ``loid`` is Reddit's logged-out visitor id.
            required_cookie_names=frozenset({"reddit_session"}),
        ),
        SiteSessionPolicy(
            "pinterest.com",
            ProviderKey.PINTEREST,
            "https://www.pinterest.com/",
            required_cookie_names=frozenset({"_auth", "_pinterest_sess"}),
            requirement=CookieRequirement.ALL,
        ),
        SiteSessionPolicy(
            "youku.com",
            ProviderKey.YOUKU,
            "https://www.youku.com/",
            entitlement=SessionEntitlement.ACCOUNT_ENTITLED_FULL_VIDEO,
            required_cookie_names=frozenset({"P_sck"}),
        ),
        SiteSessionPolicy(
            "v.qq.com",
            ProviderKey.QQVIDEO,
            "https://v.qq.com/",
            entitlement=SessionEntitlement.ACCOUNT_ENTITLED_FULL_VIDEO,
            required_cookie_names=frozenset({"v_vuserid", "v_vusession"}),
            requirement=CookieRequirement.ALL,
        ),
        SiteSessionPolicy(
            "weixin.qq.com",
            ProviderKey.WECHAT_CHANNELS,
            "https://yuanbao.tencent.com/",
            required_cookie_names=frozenset({"hy_user", "hy_token"}),
            requirement=CookieRequirement.ALL,
            header_plugin=HeaderPlugin.YUANBAO,
        ),
    )
}
_KNOWN_SITES = {policy.site: policy for policy in _KNOWN_POLICIES.values()}


def known_site_policy(provider_key: str) -> SiteSessionPolicy | None:
    try:
        return _KNOWN_POLICIES.get(ProviderKey(provider_key))
    except ValueError:
        return None


def known_session_provider_keys() -> frozenset[str]:
    return frozenset(str(key) for key in _KNOWN_POLICIES)


def known_session_sites() -> tuple[str, ...]:
    return tuple(_KNOWN_SITES)


def site_policy(site: str) -> SiteSessionPolicy:
    """Policy for a stored site key: a known provider's key or a registrable domain."""
    known = _KNOWN_SITES.get(site)
    if known is not None:
        return known
    if registrable_site(site) != site:
        raise InvalidSessionSite(
            "unknown session sites are keyed by registrable domain"
        )
    return SiteSessionPolicy(site, None, f"https://{site}/")


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
