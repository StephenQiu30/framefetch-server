"""Merge Registry declarations with the administrator-maintained catalog."""

from dataclasses import replace

from app.services.provider_catalog import ProviderCatalogRepository
from app.services.provider_types import ProviderIdentity, ProviderSupportStatus
from app.services.providers import ProviderStatusView


class ProviderStatusService:
    def __init__(
        self,
        baselines: tuple[ProviderStatusView, ...],
        *,
        catalog: ProviderCatalogRepository,
    ) -> None:
        self._baselines = {item.key: item for item in baselines}
        self._catalog = catalog

    async def list(self) -> tuple[ProviderStatusView, ...]:
        entries = await self._catalog.list_entries(visible_only=True)
        return tuple(
            replace(self._baselines[item.key], display_name=item.display_name)
            if item.key in self._baselines
            else ProviderStatusView(
                key=item.key,
                display_name=item.display_name,
                registered=False,
                extractor_exists=False,
                capabilities=(),
                identity=ProviderIdentity.NONE,
                status=ProviderSupportStatus.UNSUPPORTED,
                user_action="该平台尚未接入解析引擎。",
            )
            for item in entries
        )
