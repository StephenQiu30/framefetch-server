"""Attest an existing full-video job: python -m app.workers.canary.attest ..."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from app.core.config import get_settings_for_role
from app.core.db import create_engine, create_session_factory
from app.core.security.url_cipher import URLCipher
from app.integrations.object_storage import MinioObjectStorage
from app.integrations.provider_analysis_evidence import (
    SqlAlchemyAnalysisCanaryEvidenceReader,
)
from app.integrations.url_security import FernetUrlEnvelope
from app.repositories.providers.canary_repository import (
    SqlAlchemyProviderCanaryRepository,
)
from app.services.provider_analysis_canary import (
    AnalysisCanaryTarget,
    CanaryObjectStorage,
    ProviderAnalysisCanaryService,
)
from app.workers.canary.targets import ProviderCanaryTarget, parse_canary_targets
from app.workers.runner.provider_registry import (
    configure_provider_instances,
    provider_profile,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Persist full-video Agent/report evidence for a canary target."
    )
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--analysis-job-id", required=True, type=UUID)
    return parser.parse_args()


def _select_target(
    targets: tuple[ProviderCanaryTarget, ...], target_id: str
) -> AnalysisCanaryTarget:
    matches = tuple(item for item in targets if item.target_id == target_id)
    if not matches:
        raise ValueError("configured canary target does not exist")
    first = matches[0]
    profile = provider_profile(first.safe_url())
    return AnalysisCanaryTarget(
        first.target_id,
        first.provider_key,
        profile.version,
        first.access_mode,
        profile.egress_pool,
        profile.client_profile_id,
        first.safe_url(),
    )


async def _run(target_id: str, analysis_job_id: UUID) -> int:
    settings = get_settings_for_role("worker")
    configure_provider_instances(settings.peertube_allowed_instances)
    target = _select_target(
        parse_canary_targets(settings.provider_canary_targets), target_id
    )
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    repository = SqlAlchemyProviderCanaryRepository(sessions)
    service = ProviderAnalysisCanaryService(
        SqlAlchemyAnalysisCanaryEvidenceReader(sessions, bucket=settings.minio_bucket),
        repository,
        FernetUrlEnvelope(
            URLCipher(settings.url_encryption_key.get_secret_value().encode()),
            key_id=settings.url_encryption_key_id,
        ),
        cast(CanaryObjectStorage, MinioObjectStorage(settings)),
        now=lambda: datetime.now(UTC),
    )
    try:
        result = await service.attest(target, analysis_job_id)
    finally:
        await engine.dispose()
    print(
        json.dumps(
            {
                "target_id": result.target_id,
                "provider_key": result.provider_key,
                "stage": result.stage.value,
                "outcome": result.outcome.value,
                "stable_error_code": result.stable_error_code,
            },
            separators=(",", ":"),
        )
    )
    return 0 if result.stable_error_code is None else 1


def main() -> None:
    arguments = _arguments()
    raise SystemExit(asyncio.run(_run(arguments.target_id, arguments.analysis_job_id)))


if __name__ == "__main__":
    main()
