"""Public policy names; no credentials, endpoint discovery or implicit fallback."""

from enum import StrEnum

from app.services.provider_types import ProviderAccessMode, ProviderKey

# Explicit platform-native public routes. This set is decided before any I/O;
# authentication failures never switch a session platform into this set.
NATIVE_PUBLIC_PROVIDERS = frozenset(
    {
        ProviderKey.BILIBILI,
        ProviderKey.TIKTOK,
        ProviderKey.KUAISHOU,
        ProviderKey.VIMEO,
        ProviderKey.TWITCH,
        ProviderKey.WEIBO,
        ProviderKey.SNAPCHAT,
        ProviderKey.LINKEDIN,
        ProviderKey.TELEGRAM,
        ProviderKey.KICK,
        ProviderKey.TUMBLR,
        ProviderKey.HONGGUO_WEB,
    }
)


def execution_access_mode(provider_key: str) -> ProviderAccessMode:
    return (
        ProviderAccessMode.ANONYMOUS
        if provider_key in NATIVE_PUBLIC_PROVIDERS
        else ProviderAccessMode.OPERATOR_MANAGED
    )


class ProviderAccessPolicy(StrEnum):
    PUBLIC = "public"
    PUBLIC_SESSION = "public_session"
    OPERATOR_PUBLIC = "operator_public"
    PERSONAL_ENTITLED = "personal_entitled"

    @property
    def access_mode(self) -> ProviderAccessMode:
        return {
            ProviderAccessPolicy.PUBLIC: ProviderAccessMode.ANONYMOUS,
            ProviderAccessPolicy.PUBLIC_SESSION: ProviderAccessMode.GUEST,
            ProviderAccessPolicy.OPERATOR_PUBLIC: ProviderAccessMode.OPERATOR_MANAGED,
            ProviderAccessPolicy.PERSONAL_ENTITLED: ProviderAccessMode.OPERATOR_MANAGED,
        }[self]


def provider_access_policies(
    provider_key: str, access_modes: tuple[ProviderAccessMode, ...]
) -> tuple[ProviderAccessPolicy, ...]:
    """Only approved policies are selectable; visitor maintenance remains gated."""
    policies = []
    if ProviderAccessMode.ANONYMOUS in access_modes:
        policies.append(ProviderAccessPolicy.PUBLIC)
    if ProviderAccessMode.GUEST in access_modes:
        policies.append(ProviderAccessPolicy.PUBLIC_SESSION)
    if ProviderAccessMode.OPERATOR_MANAGED in access_modes:
        policies.append(
            ProviderAccessPolicy.PERSONAL_ENTITLED
            if provider_key in {ProviderKey.YOUKU, ProviderKey.QQVIDEO}
            else ProviderAccessPolicy.OPERATOR_PUBLIC
        )
    return tuple(policies)


def default_access_policy(
    provider_key: str,
    access_modes: tuple[ProviderAccessMode, ...],
    *,
    guest_configured: bool = False,
) -> ProviderAccessPolicy:
    # Input-only clients do not choose infrastructure or credentials. Prefer
    # public access; deployments may explicitly select an authorized session.
    # An available endpoint alone must never increase the request's privileges.
    policies = provider_access_policies(provider_key, access_modes)
    if not policies:
        raise ValueError("provider has no admitted access policy")
    if guest_configured and ProviderAccessPolicy.PUBLIC_SESSION in policies:
        return ProviderAccessPolicy.PUBLIC_SESSION
    return policies[0]
