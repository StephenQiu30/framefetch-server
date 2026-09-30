"""Finite capabilities and execution preparation for database/Workflow tests."""

from datetime import datetime

from app.repositories.downloads.intent_repository import IntentRepository
from app.schemas.resolution import RunnerEngineCatalogResponse
from app.services.downloads.resolution import (
    ResolutionCapability,
    ResolutionPlan,
    ResolutionPreparation,
)
from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_failures import FailureClass
from app.services.provider_types import (
    MediaHandoff,
    ProviderAccessContextRef,
    ProviderAccessMode,
    ProviderCapability,
    ProviderSessionSource,
    ResolutionExecutionKind,
    ResolutionStrategy,
)


def capability_for(
    policy: ProviderAccessPolicy,
    *,
    provider_key: str = "fixture",
    version: str = "fixture",
) -> ResolutionCapability:
    anonymous = ResolutionStrategy(
        "yt-dlp-anonymous",
        "yt-dlp",
        version,
        ResolutionExecutionKind.HTTP,
        ProviderAccessMode.ANONYMOUS,
        ProviderSessionSource.NONE,
        (),
        frozenset(),
        MediaHandoff.HTTP_TRANSFERABLE,
        "semantic-media-and-artifact",
    )
    session = ResolutionStrategy(
        "yt-dlp-session",
        "yt-dlp",
        version,
        ResolutionExecutionKind.HTTP,
        ProviderAccessMode.OPERATOR_MANAGED,
        ProviderSessionSource.CHROME_SOURCE,
        ("approved_session",),
        frozenset({FailureClass.AUTH_REQUIRED, FailureClass.CHALLENGE_REQUIRED}),
        MediaHandoff.HTTP_TRANSFERABLE,
        "semantic-media-and-artifact",
    )
    strategies = (
        (session,)
        if policy is ProviderAccessPolicy.PERSONAL_ENTITLED
        else (
            (anonymous, session)
            if policy is ProviderAccessPolicy.OPERATOR_PUBLIC
            else (anonymous,)
        )
    )
    return ResolutionCapability(
        provider_key,
        version,
        policy,
        (ProviderCapability.SINGLE_VIDEO,),
        strategies,
        "a" * 64,
    )


def catalog_document(capability: ResolutionCapability) -> dict[str, object]:
    return RunnerEngineCatalogResponse(
        engine_version="fixture",
        engine_commit="a" * 40,
        expected_engine_commit="a" * 40,
        pin_matches=True,
        bundled_plugins_sha256="b" * 64,
        manifest_id="c" * 64,
        candidates=({"key": "Generic", "name": "generic", "upstream_working": True},),
        resolution_capabilities=(capability,),
    ).model_dump(mode="json")


def preparation_for(
    plan: ResolutionPlan, strategy_id: str, *, credential: str = "fixture-session"
) -> ResolutionPreparation:
    strategy = plan.strategy(strategy_id)
    return ResolutionPreparation(
        ProviderAccessContextRef(
            provider_key=plan.capability.provider_key,
            profile_version=plan.capability.profile_version,
            access_mode=strategy.access_mode,
            credential_version_id=None
            if strategy.session_source is ProviderSessionSource.NONE
            else credential,
            egress_affinity_id="fixture-egress",
            client_profile_id="yt-dlp-default",
            attestation_provider_version=None,
            engine_commit="a" * 40,
            runtime_revision="b" * 64,
            strategy_id=strategy_id,
            adapter_revision=strategy.adapter_revision,
            session_source_id=None
            if strategy.session_source is ProviderSessionSource.NONE
            else "chrome_source",
            protocol_capabilities=("http-media",),
        ),
        "c" * 32,
    )


async def start_attempt(
    repo: IntentRepository,
    intent_id,
    generation: int,
    preparation_id: str,
    *,
    now: datetime,
    credential: str = "fixture-session",
):
    preparing = await repo.claim_preparation(
        intent_id, generation, preparation_id, now=now
    )
    if preparing is None or not preparing.newly_claimed:
        return None
    snapshot = preparing.intent
    plan = snapshot.resolution_plan or ResolutionPlan(
        capability_for(snapshot.access_policy), generation
    )
    if snapshot.resolution_plan is None:
        snapshot = await repo.bind_plan(snapshot, plan, now=now)
    return await repo.begin_attempt(
        snapshot,
        preparation_for(plan, snapshot.next_strategy_id, credential=credential),
        now=now,
    )
