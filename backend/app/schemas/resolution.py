"""Validated codecs for internal capabilities and persistent resolution facts."""

from pydantic import Field, TypeAdapter, field_validator

from app.schemas.engine_catalog import EngineCatalogResponse
from app.services.downloads.resolution import ResolutionCapability, ResolutionPlan
from app.services.provider_failures import ProviderFailure

RESOLUTION_PLAN = TypeAdapter(ResolutionPlan)
PROVIDER_FAILURE = TypeAdapter(ProviderFailure)


class RunnerEngineCatalogResponse(EngineCatalogResponse):
    resolution_capabilities: tuple[ResolutionCapability, ...] = Field(
        min_length=1, max_length=128
    )

    @field_validator("resolution_capabilities")
    @classmethod
    def _unique_providers(
        cls, capabilities: tuple[ResolutionCapability, ...]
    ) -> tuple[ResolutionCapability, ...]:
        keys = tuple(item.provider_key for item in capabilities)
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate resolution provider")
        return capabilities
