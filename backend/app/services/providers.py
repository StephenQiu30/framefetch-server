"""Public Provider declarations, without probe or release admission state."""

from dataclasses import dataclass

from app.services.provider_types import (
    ProviderCapability,
    ProviderIdentity,
    ProviderSupportStatus,
)


@dataclass(frozen=True, slots=True)
class ProviderStatusView:
    key: str
    display_name: str
    registered: bool
    extractor_exists: bool
    capabilities: tuple[ProviderCapability, ...]
    identity: ProviderIdentity
    status: ProviderSupportStatus
    user_action: str | None
    hosts: tuple[str, ...] = ()
    host_suffixes: tuple[str, ...] = ()

    @property
    def download_supported(self) -> bool:
        downloadable = {
            ProviderCapability.SINGLE_VIDEO,
            ProviderCapability.SHORT_VIDEO,
            ProviderCapability.CLIP_OR_VOD,
        }
        return (
            self.registered
            and self.extractor_exists
            and self.status
            not in {ProviderSupportStatus.DISABLED, ProviderSupportStatus.UNSUPPORTED}
            and bool(downloadable.intersection(self.capabilities))
        )
