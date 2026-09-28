from __future__ import annotations

import json
from urllib.parse import urlsplit

from app.services.provider_types import ProviderAccessMode, ProviderCanaryStage
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_registry import provider_request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError


class ProviderCanaryTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    provider_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    stage: ProviderCanaryStage
    access_mode: ProviderAccessMode
    url: SecretStr

    def safe_url(self) -> str:
        return self.url.get_secret_value()


def parse_canary_targets(value: SecretStr) -> tuple[ProviderCanaryTarget, ...]:
    try:
        document = json.loads(value.get_secret_value())
        if not isinstance(document, list):
            raise ValueError
        targets = tuple(ProviderCanaryTarget.model_validate(item) for item in document)
        _validate_targets(targets)
    except (
        TypeError,
        ValueError,
        ValidationError,
        json.JSONDecodeError,
        RunnerFailure,
    ):
        raise ValueError("provider canary targets are invalid") from None
    return targets


def validate_canary_target_routes(
    targets: tuple[ProviderCanaryTarget, ...],
    operator_provider_keys: frozenset[str],
) -> None:
    missing = sorted(
        {
            target.provider_key
            for target in targets
            if target.access_mode is ProviderAccessMode.OPERATOR_MANAGED
            and target.provider_key not in operator_provider_keys
        }
    )
    if missing:
        raise ValueError(
            "provider canary operator targets require matching runner endpoints: "
            + ",".join(missing)
        )


def _validate_targets(targets: tuple[ProviderCanaryTarget, ...]) -> None:
    identities: set[tuple[str, ProviderCanaryStage]] = set()
    for target in targets:
        if target.stage is ProviderCanaryStage.ANALYSIS:
            # Analysis evidence is accepted only by the explicit attestation
            # command after the normal RabbitMQ/Agent/report workflow succeeds.
            raise ValueError
        identity = (target.target_id, target.stage)
        if identity in identities:
            raise ValueError
        identities.add(identity)
        url = target.safe_url()
        parsed = urlsplit(url)
        resolved = provider_request(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or resolved.profile.key != target.provider_key
            or target.access_mode is not ProviderAccessMode.OPERATOR_MANAGED
            or target.access_mode not in resolved.profile.access_modes
        ):
            raise ValueError
        if not resolved.request_url:
            raise ValueError

    grouped: dict[str, tuple[str, str, ProviderAccessMode]] = {}
    for target in targets:
        target_reference = (
            target.provider_key,
            target.safe_url(),
            target.access_mode,
        )
        existing = grouped.setdefault(target.target_id, target_reference)
        if existing != target_reference:
            raise ValueError
