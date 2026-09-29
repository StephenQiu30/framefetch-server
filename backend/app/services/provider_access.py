"""Public policy names; no credentials, endpoint discovery or implicit fallback."""

from enum import StrEnum

from app.services.provider_types import ProviderAccessMode, ProviderKey


class ProviderAccessPolicy(StrEnum):
    PUBLIC = "public"
    # Historical records only: the retired visitor route.
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
    """Only approved policies are selectable."""
    policies = []
    if ProviderAccessMode.ANONYMOUS in access_modes:
        policies.append(ProviderAccessPolicy.PUBLIC)
    if ProviderAccessMode.OPERATOR_MANAGED in access_modes:
        policies.append(
            ProviderAccessPolicy.PERSONAL_ENTITLED
            if provider_key in {ProviderKey.YOUKU, ProviderKey.QQVIDEO}
            else ProviderAccessPolicy.OPERATOR_PUBLIC
        )
    return tuple(policies)
