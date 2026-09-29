from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from app.services.provider_access import ProviderAccessPolicy
from app.services.provider_canaries import (
    ProviderEvidenceScope,
    ProviderRuntimeContextReader,
)
from app.services.provider_canaries import (
    ProviderStatusService as _ProviderStatusService,
)
from app.services.provider_catalog import ProviderCatalogEntry
from app.services.provider_types import (
    ProviderAccessContextRef,
    ProviderAccessMode,
    ProviderAccessState,
    ProviderCanaryOutcome,
    ProviderCanaryResult,
    ProviderCanaryStage,
    ProviderCapability,
    ProviderSupportStatus,
)
from app.services.providers import ProviderStatusView
from app.workers.runner.version import YTDLP_ENGINE_COMMIT

NOW = datetime(2026, 8, 11, 6, tzinfo=UTC)


def access_context(
    *,
    provider_key: str = "vimeo",
    profile_version: str = "1",
    access_mode: ProviderAccessMode = ProviderAccessMode.ANONYMOUS,
    credential_version_id: str | None = None,
    egress_affinity_id: str = "default",
    client_profile_id: str = "yt-dlp-default",
    attestation_provider_version: str | None = None,
    engine_commit: str = YTDLP_ENGINE_COMMIT,
) -> ProviderAccessContextRef:
    if (
        access_mode is not ProviderAccessMode.ANONYMOUS
        and credential_version_id is None
    ):
        credential_version_id = "credential-current"
    return ProviderAccessContextRef(
        provider_key=provider_key,
        profile_version=profile_version,
        access_mode=access_mode,
        credential_version_id=credential_version_id,
        egress_affinity_id=egress_affinity_id,
        client_profile_id=client_profile_id,
        attestation_provider_version=attestation_provider_version,
        engine_commit=engine_commit,
        runtime_revision="a" * 64,
    )


def test_legacy_context_cannot_share_current_runtime_generation() -> None:
    current = access_context()
    legacy_document = current.to_document()
    legacy_document.pop("runtime_revision")
    legacy = ProviderAccessContextRef.from_document(legacy_document)

    assert legacy.runtime_revision == "legacy"
    assert legacy.generation_id != current.generation_id


class ContextReader:
    def __init__(
        self,
        contexts: tuple[ProviderAccessContextRef, ...] = (access_context(),),
    ) -> None:
        self.contexts = contexts
        self.requests: list[Mapping[str, ProviderAccessMode]] = []

    async def contexts_for_providers(
        self,
        requested: Mapping[str, ProviderAccessMode],
    ) -> Mapping[str, ProviderAccessContextRef]:
        self.requests.append(requested)
        return {
            context.provider_key: context
            for context in self.contexts
            if requested.get(context.provider_key) is context.access_mode
        }


def ProviderStatusService(  # noqa: N802
    reader: Reader,
    baselines: tuple[ProviderStatusView, ...],
    *,
    now: Callable[[], datetime],
    context_reader: ProviderRuntimeContextReader | None = None,
    approved_keys: frozenset[str] = frozenset(),
    catalog: Catalog | None = None,
) -> _ProviderStatusService:
    return _ProviderStatusService(
        reader,
        baselines,
        now=now,
        context_reader=context_reader or ContextReader(),
        approved_keys=approved_keys,
        catalog=catalog,  # type: ignore[arg-type]
    )


class Reader:
    def __init__(
        self,
        results: tuple[ProviderCanaryResult, ...],
        *,
        key: str = "vimeo",
    ) -> None:
        self.results = results
        self.key = key

    async def list_recent(
        self,
        *,
        limit_per_provider_stage: int,
        scopes: Mapping[str, ProviderEvidenceScope],
    ) -> dict[str, tuple[ProviderCanaryResult, ...]]:
        assert limit_per_provider_stage == 32
        return {self.key: self.results}


class Catalog:
    async def list_entries(
        self, *, visible_only: bool = False
    ) -> tuple[ProviderCatalogEntry, ...]:
        assert visible_only is True
        return (
            ProviderCatalogEntry(
                key="custom",
                display_name="Custom platform",
                sort_order=1,
                is_visible=True,
                created_at=NOW,
                updated_at=NOW,
            ),
            ProviderCatalogEntry(
                key="vimeo",
                display_name="Vimeo 视频",
                sort_order=2,
                is_visible=True,
                created_at=NOW,
                updated_at=NOW,
            ),
        )


def baseline(
    status: ProviderSupportStatus = ProviderSupportStatus.UNKNOWN,
) -> ProviderStatusView:
    return ProviderStatusView(
        key="vimeo",
        display_name="Vimeo",
        profile_version="1",
        registered=True,
        extractor_exists=True,
        capabilities=(ProviderCapability.SINGLE_VIDEO,),
        access_modes=(ProviderAccessMode.ANONYMOUS,),
        status=status,
        last_checked_at=None,
        last_check_succeeded=None,
        download_available=False,
        last_media_verified_at=None,
        last_verified_at=None,
        user_action=(None if status is ProviderSupportStatus.VERIFIED else "待验证"),
    )


def result(
    minutes: int,
    *,
    stage: ProviderCanaryStage = ProviderCanaryStage.METADATA,
    error: str | None = None,
) -> ProviderCanaryResult:
    return ProviderCanaryResult(
        target_id="vimeo-owned-1",
        provider_key="vimeo",
        profile_version="1",
        stage=stage,
        access_mode=ProviderAccessMode.ANONYMOUS,
        outcome=(
            ProviderCanaryOutcome.FAILED
            if error is not None
            else ProviderCanaryOutcome.SUCCEEDED
        ),
        stable_error_code=error,
        checked_at=NOW - timedelta(minutes=minutes),
        duration_ms=100,
        engine_commit=YTDLP_ENGINE_COMMIT,
        egress_affinity_id="default",
        client_profile_id="yt-dlp-default",
        context_generation_id=access_context().generation_id,
    )


@pytest.mark.asyncio
async def test_unapproved_profile_stays_unknown_after_media_evidence() -> None:
    results = (
        result(0),
        result(15, stage=ProviderCanaryStage.ANALYSIS),
        result(30),
        result(60, stage=ProviderCanaryStage.MEDIA),
        result(90),
        result(120, error="inspection_timeout"),
    )
    service = ProviderStatusService(Reader(results), (baseline(),), now=lambda: NOW)

    view = (await service.list())[0]

    assert view.status is ProviderSupportStatus.UNKNOWN
    assert view.last_media_verified_at == NOW - timedelta(minutes=60)
    assert view.last_verified_at == NOW - timedelta(minutes=15)
    assert view.user_action == (
        "公开样本已完成真实下载验证；完整视频分析链路仍待验证。"
    )


@pytest.mark.asyncio
async def test_approved_profile_recovers_after_fresh_canary_evidence() -> None:
    results = (
        result(0),
        result(15, stage=ProviderCanaryStage.ANALYSIS),
        result(30),
        result(60, stage=ProviderCanaryStage.MEDIA),
        result(90),
        result(120, error="inspection_timeout"),
    )
    service = ProviderStatusService(
        Reader(results),
        (baseline(ProviderSupportStatus.VERIFIED),),
        now=lambda: NOW,
    )

    assert (await service.list())[0].status is ProviderSupportStatus.VERIFIED


@pytest.mark.asyncio
async def test_supported_download_is_explicit_with_conditional_session() -> None:
    results = (
        result(0),
        result(30, stage=ProviderCanaryStage.MEDIA),
    )
    service = ProviderStatusService(
        Reader(results),
        (baseline(ProviderSupportStatus.ACCESS_REQUIRED),),
        now=lambda: NOW,
    )

    view = (await service.list())[0]

    assert view.download_supported is True
    assert view.download_available is True
    assert view.status is ProviderSupportStatus.ACCESS_REQUIRED
    assert view.user_action == (
        "真实下载已完成验证；当前链接仍可能因平台授权或验证要求失败。"
    )
    assert view.access_state is ProviderAccessState.AUTHORIZATION_REQUIRED


@pytest.mark.asyncio
async def test_platform_challenge_enters_recoverable_authorization_state() -> None:
    service = ProviderStatusService(
        Reader(
            (
                replace(
                    result(0, error="egress_challenged"),
                    access_mode=ProviderAccessMode.OPERATOR_MANAGED,
                    context_generation_id=access_context(
                        access_mode=ProviderAccessMode.OPERATOR_MANAGED
                    ).generation_id,
                ),
            )
        ),
        (
            replace(
                baseline(),
                access_modes=(
                    ProviderAccessMode.ANONYMOUS,
                    ProviderAccessMode.OPERATOR_MANAGED,
                ),
            ),
        ),
        now=lambda: NOW,
        context_reader=ContextReader(
            (access_context(access_mode=ProviderAccessMode.OPERATOR_MANAGED),)
        ),
    )

    view = (await service.list())[0]

    assert view.status is ProviderSupportStatus.ACCESS_REQUIRED
    assert view.access_state is ProviderAccessState.AUTHORIZATION_REQUIRED
    assert "部署机器已连接的 Chrome 会话" in (view.user_action or "")
    assert "Chrome 扩展已连接" in (view.user_action or "")


def test_access_state_projection_uses_the_selected_route_not_all_capabilities() -> None:
    public = baseline(ProviderSupportStatus.VERIFIED)
    public_with_operator_capability = replace(
        public,
        access_modes=(
            ProviderAccessMode.ANONYMOUS,
            ProviderAccessMode.OPERATOR_MANAGED,
        ),
        default_access_policy_id=ProviderAccessPolicy.PUBLIC,
    )
    operator = replace(
        public,
        access_modes=(ProviderAccessMode.OPERATOR_MANAGED,),
    )

    assert public.access_state is ProviderAccessState.PUBLIC_PROBE
    assert (
        public_with_operator_capability.access_state is ProviderAccessState.PUBLIC_PROBE
    )
    assert operator.access_state is ProviderAccessState.OPERATOR_PROBE


@pytest.mark.asyncio
async def test_release_verification_survives_without_current_canary() -> None:
    service = ProviderStatusService(
        Reader(()),
        (baseline(ProviderSupportStatus.VERIFIED),),
        now=lambda: NOW,
    )

    view = (await service.list())[0]

    assert view.status is ProviderSupportStatus.VERIFIED
    assert view.last_verified_at is None
    assert view.user_action is None


@pytest.mark.asyncio
async def test_runtime_context_failure_fails_closed_without_using_stale_evidence() -> (
    None
):
    class UnavailableContextReader:
        async def contexts_for_providers(
            self,
            requested: Mapping[str, ProviderAccessMode],
        ) -> Mapping[str, ProviderAccessContextRef]:
            assert requested == {"vimeo": ProviderAccessMode.ANONYMOUS}
            raise TimeoutError

    service = ProviderStatusService(
        Reader((result(0, stage=ProviderCanaryStage.MEDIA),)),
        (baseline(ProviderSupportStatus.VERIFIED),),
        now=lambda: NOW,
        context_reader=UnavailableContextReader(),
    )

    view = (await service.list())[0]

    assert view.status is ProviderSupportStatus.DEGRADED
    assert view.last_checked_at is None
    assert view.download_available is False


@pytest.mark.asyncio
async def test_partial_runtime_evidence_does_not_revoke_release_verification() -> None:
    service = ProviderStatusService(
        Reader((result(0), result(30, stage=ProviderCanaryStage.MEDIA))),
        (baseline(ProviderSupportStatus.VERIFIED),),
        now=lambda: NOW,
    )

    view = (await service.list())[0]

    assert view.status is ProviderSupportStatus.VERIFIED
    assert view.last_checked_at == NOW
    assert view.last_check_succeeded is True
    assert view.download_available is True


@pytest.mark.asyncio
async def test_evidence_from_an_old_profile_version_is_ignored() -> None:
    old_context = access_context(profile_version="old")
    old = replace(
        result(0),
        profile_version="old",
        context_generation_id=old_context.generation_id,
    )
    service = ProviderStatusService(
        Reader((old,)),
        (baseline(ProviderSupportStatus.VERIFIED),),
        now=lambda: NOW,
    )

    view = (await service.list())[0]

    assert view.status is ProviderSupportStatus.VERIFIED
    assert view.last_checked_at is None
    assert view.last_check_succeeded is None
    assert view.download_available is False


@pytest.mark.asyncio
async def test_evidence_from_an_old_engine_is_ignored() -> None:
    old_context = access_context(engine_commit="previous-engine")
    old = replace(
        result(0),
        engine_commit="previous-engine",
        context_generation_id=old_context.generation_id,
    )
    service = ProviderStatusService(
        Reader((old,)),
        (baseline(ProviderSupportStatus.VERIFIED),),
        now=lambda: NOW,
    )

    view = (await service.list())[0]

    assert view.status is ProviderSupportStatus.VERIFIED
    assert view.last_checked_at is None
    assert view.download_available is False


@pytest.mark.asyncio
async def test_evidence_from_a_runtime_disabled_access_mode_is_ignored() -> None:
    operator_context = access_context(
        access_mode=ProviderAccessMode.OPERATOR_MANAGED,
    )
    operator_results = (
        replace(
            result(0, error="provider_auth_required"),
            access_mode=ProviderAccessMode.OPERATOR_MANAGED,
            context_generation_id=operator_context.generation_id,
        ),
        replace(
            result(30, stage=ProviderCanaryStage.MEDIA),
            access_mode=ProviderAccessMode.OPERATOR_MANAGED,
            context_generation_id=operator_context.generation_id,
        ),
    )
    service = ProviderStatusService(
        Reader(operator_results),
        (baseline(ProviderSupportStatus.VERIFIED),),
        now=lambda: NOW,
    )

    view = (await service.list())[0]

    assert view.status is ProviderSupportStatus.VERIFIED
    assert view.last_checked_at is None
    assert view.last_check_succeeded is None
    assert view.download_available is False
    assert view.last_media_verified_at is None


@pytest.mark.asyncio
async def test_old_runtime_route_cannot_keep_download_status_available() -> None:
    current_context = access_context(
        engine_commit="current-engine",
        egress_affinity_id="provider:vimeo",
        client_profile_id="current-client",
    )
    current_failure = replace(
        result(1, error="provider_verification_failed"),
        engine_commit=current_context.engine_commit,
        egress_affinity_id=current_context.egress_affinity_id,
        client_profile_id=current_context.client_profile_id,
        context_generation_id=current_context.generation_id,
    )
    # A late result from the old route is newer, but can never reactivate it.
    old_media_success = result(0, stage=ProviderCanaryStage.MEDIA)
    service = ProviderStatusService(
        Reader((current_failure, old_media_success)),
        (baseline(ProviderSupportStatus.ACCESS_REQUIRED),),
        now=lambda: NOW,
        context_reader=ContextReader((current_context,)),
    )

    view = (await service.list())[0]

    assert view.last_checked_at == NOW - timedelta(minutes=1)
    assert view.last_check_succeeded is False
    assert view.download_available is False
    assert view.last_media_verified_at is None


@pytest.mark.parametrize(
    ("old_context", "current_context"),
    (
        (
            access_context(
                access_mode=ProviderAccessMode.OPERATOR_MANAGED,
                credential_version_id="credential-current",
            ),
            access_context(
                access_mode=ProviderAccessMode.OPERATOR_MANAGED,
                credential_version_id="credential-v2",
            ),
        ),
        (
            access_context(attestation_provider_version="bgutil"),
            access_context(attestation_provider_version="bgutil-v2"),
        ),
    ),
)
async def test_credential_or_attestation_rotation_invalidates_old_evidence(
    old_context: ProviderAccessContextRef,
    current_context: ProviderAccessContextRef,
) -> None:
    access_modes = (current_context.access_mode,)
    stale_success = replace(
        result(0, stage=ProviderCanaryStage.MEDIA),
        access_mode=old_context.access_mode,
        context_generation_id=old_context.generation_id,
    )
    current_failure = replace(
        result(1, stage=ProviderCanaryStage.MEDIA, error="download_timeout"),
        access_mode=current_context.access_mode,
        context_generation_id=current_context.generation_id,
    )
    current_baseline = replace(
        baseline(ProviderSupportStatus.ACCESS_REQUIRED),
        access_modes=access_modes,
    )
    service = ProviderStatusService(
        Reader((stale_success, current_failure)),
        (current_baseline,),
        now=lambda: NOW,
        context_reader=ContextReader((current_context,)),
    )

    view = (await service.list())[0]

    assert old_context.generation_id != current_context.generation_id
    assert view.last_checked_at == NOW - timedelta(minutes=1)
    assert view.last_check_succeeded is False
    assert view.download_available is False


@pytest.mark.asyncio
async def test_mixed_unknown_status_uses_operator_download_evidence() -> None:
    operator_context = access_context(
        access_mode=ProviderAccessMode.OPERATOR_MANAGED,
    )
    operator_media = replace(
        result(0, stage=ProviderCanaryStage.MEDIA),
        access_mode=ProviderAccessMode.OPERATOR_MANAGED,
        context_generation_id=operator_context.generation_id,
    )
    operator_baseline = replace(
        baseline(),
        access_modes=(
            ProviderAccessMode.ANONYMOUS,
            ProviderAccessMode.OPERATOR_MANAGED,
        ),
    )
    service = ProviderStatusService(
        Reader((operator_media,)),
        (operator_baseline,),
        now=lambda: NOW,
        context_reader=ContextReader((operator_context,)),
    )

    view = (await service.list())[0]

    assert view.last_checked_at == NOW
    assert view.last_check_succeeded is True
    assert view.download_available is True
    assert view.last_media_verified_at == NOW


@pytest.mark.asyncio
async def test_mixed_access_required_status_uses_operator_download_evidence() -> None:
    operator_context = access_context(
        access_mode=ProviderAccessMode.OPERATOR_MANAGED,
    )
    operator_download = replace(
        result(0, stage=ProviderCanaryStage.MEDIA),
        target_id="download:00000000-0000-4000-8000-000000000001",
        access_mode=ProviderAccessMode.OPERATOR_MANAGED,
        context_generation_id=operator_context.generation_id,
    )
    mixed_baseline = replace(
        baseline(ProviderSupportStatus.ACCESS_REQUIRED),
        access_modes=(
            ProviderAccessMode.ANONYMOUS,
            ProviderAccessMode.OPERATOR_MANAGED,
        ),
    )
    contexts = ContextReader((operator_context,))
    service = ProviderStatusService(
        Reader((operator_download,)),
        (mixed_baseline,),
        now=lambda: NOW,
        context_reader=contexts,
    )

    view = (await service.list())[0]

    assert contexts.requests == [{"vimeo": ProviderAccessMode.OPERATOR_MANAGED}]
    assert view.status is ProviderSupportStatus.ACCESS_REQUIRED
    assert view.last_checked_at == NOW
    assert view.last_check_succeeded is True
    assert view.download_available is True
    assert view.last_media_verified_at == NOW
    assert view.last_verified_at is None
    assert view.user_action == (
        "真实下载已完成验证；当前链接仍可能因平台授权或验证要求失败。"
    )


@pytest.mark.asyncio
async def test_mixed_verified_status_uses_operator_evidence_scope() -> None:
    operator_context = access_context(
        access_mode=ProviderAccessMode.OPERATOR_MANAGED,
    )
    operator_media = replace(
        result(0, stage=ProviderCanaryStage.MEDIA),
        access_mode=ProviderAccessMode.OPERATOR_MANAGED,
        context_generation_id=operator_context.generation_id,
    )
    mixed_baseline = replace(
        baseline(ProviderSupportStatus.VERIFIED),
        access_modes=(
            ProviderAccessMode.ANONYMOUS,
            ProviderAccessMode.OPERATOR_MANAGED,
        ),
    )
    contexts = ContextReader((operator_context,))
    service = ProviderStatusService(
        Reader((operator_media,)),
        (mixed_baseline,),
        now=lambda: NOW,
        context_reader=contexts,
    )

    view = (await service.list())[0]

    assert contexts.requests == [{"vimeo": ProviderAccessMode.OPERATOR_MANAGED}]
    assert view.status is ProviderSupportStatus.VERIFIED
    assert view.last_checked_at == NOW
    assert view.last_check_succeeded is True
    assert view.download_available is True
    assert view.last_media_verified_at == NOW


@pytest.mark.asyncio
async def test_operator_only_status_uses_attributed_operator_evidence() -> None:
    operator_context = access_context(
        access_mode=ProviderAccessMode.OPERATOR_MANAGED,
    )
    operator_media = replace(
        result(0, stage=ProviderCanaryStage.MEDIA),
        access_mode=ProviderAccessMode.OPERATOR_MANAGED,
        context_generation_id=operator_context.generation_id,
    )
    operator_baseline = replace(
        baseline(),
        access_modes=(ProviderAccessMode.OPERATOR_MANAGED,),
    )
    service = ProviderStatusService(
        Reader((operator_media,)),
        (operator_baseline,),
        now=lambda: NOW,
        context_reader=ContextReader((operator_context,)),
    )

    view = (await service.list())[0]

    assert view.last_checked_at == NOW
    assert view.download_available is True
    assert view.last_media_verified_at == NOW
    assert view.user_action == (
        "受控线路样本已完成真实下载验证；完整视频分析链路仍待验证。"
    )


@pytest.mark.asyncio
async def test_disabled_status_is_immutable_under_runtime_evidence() -> None:
    disabled = replace(
        baseline(ProviderSupportStatus.DISABLED),
        access_modes=(),
    )
    service = ProviderStatusService(
        Reader((result(0, error="provider_auth_required"),)),
        (disabled,),
        now=lambda: NOW,
    )

    view = (await service.list())[0]

    assert view.status is ProviderSupportStatus.DISABLED
    assert view.download_supported is False
    assert view.last_checked_at is None
    assert view.download_available is False


@pytest.mark.asyncio
async def test_latest_media_failure_revokes_download_availability() -> None:
    results = (
        result(0, stage=ProviderCanaryStage.MEDIA, error="download_timeout"),
        result(60, stage=ProviderCanaryStage.MEDIA),
    )
    service = ProviderStatusService(
        Reader(results),
        (baseline(),),
        now=lambda: NOW,
    )

    view = (await service.list())[0]

    assert view.last_check_succeeded is False
    assert view.download_available is False
    assert view.last_media_verified_at == NOW - timedelta(minutes=60)


@pytest.mark.asyncio
async def test_explicitly_approved_profile_promotes_only_with_full_chain() -> None:
    results = (
        result(0),
        result(15, stage=ProviderCanaryStage.ANALYSIS),
        result(30),
        result(60, stage=ProviderCanaryStage.MEDIA),
        result(90),
        result(120, error="inspection_timeout"),
    )
    service = ProviderStatusService(
        Reader(results),
        (baseline(),),
        now=lambda: NOW,
        approved_keys=frozenset({"vimeo"}),
    )

    assert (await service.list())[0].status is ProviderSupportStatus.VERIFIED


@pytest.mark.asyncio
async def test_real_media_traffic_cannot_displace_fresh_metadata_verification() -> None:
    downloads = tuple(
        replace(
            result(minute, stage=ProviderCanaryStage.MEDIA),
            target_id=f"download:{minute}",
        )
        for minute in range(5)
    )
    evidence = (
        *downloads,
        result(5, stage=ProviderCanaryStage.METADATA),
        result(6, stage=ProviderCanaryStage.MEDIA),
        result(7, stage=ProviderCanaryStage.ANALYSIS),
    )
    service = ProviderStatusService(
        Reader(evidence),
        (baseline(),),
        now=lambda: NOW,
        approved_keys=frozenset({"vimeo"}),
    )

    view = (await service.list())[0]

    assert view.status is ProviderSupportStatus.VERIFIED
    assert view.last_verified_at == NOW - timedelta(minutes=7)
    assert view.last_media_verified_at == NOW


@pytest.mark.asyncio
async def test_explicit_approval_without_analysis_evidence_stays_unknown() -> None:
    results = (
        result(0),
        result(30),
        result(60, stage=ProviderCanaryStage.MEDIA),
        result(90),
        result(120, error="inspection_timeout"),
    )
    service = ProviderStatusService(
        Reader(results),
        (baseline(),),
        now=lambda: NOW,
        approved_keys=frozenset({"vimeo"}),
    )

    assert (await service.list())[0].status is ProviderSupportStatus.UNKNOWN


def test_rejects_approval_for_an_unregistered_provider() -> None:
    with pytest.raises(ValueError, match="not registered"):
        ProviderStatusService(
            Reader(()),
            (baseline(),),
            now=lambda: NOW,
            approved_keys=frozenset({"missing"}),
        )


@pytest.mark.asyncio
async def test_access_and_repeated_permanent_failures_override_baseline() -> None:
    access = ProviderStatusService(
        Reader((result(0, error="provider_auth_required"),)),
        (baseline(),),
        now=lambda: NOW,
    )
    blocked = ProviderStatusService(
        Reader(
            tuple(
                result(index, error="provider_content_restricted") for index in range(3)
            )
        ),
        (baseline(),),
        now=lambda: NOW,
    )

    assert (await access.list())[0].status is ProviderSupportStatus.ACCESS_REQUIRED
    assert (await blocked.list())[0].status is ProviderSupportStatus.BLOCKED


@pytest.mark.asyncio
async def test_wechat_channels_message_explains_anonymous_public_scope() -> None:
    wechat = replace(baseline(), key="wechat_channels")
    wechat_context = access_context(provider_key="wechat_channels")
    service = ProviderStatusService(
        Reader(
            (
                replace(
                    result(0, error="provider_auth_required"),
                    provider_key="wechat_channels",
                    context_generation_id=wechat_context.generation_id,
                ),
            ),
            key="wechat_channels",
        ),
        (wechat,),
        now=lambda: NOW,
        context_reader=ContextReader((wechat_context,)),
    )

    view = (await service.list())[0]

    assert view.user_action == (
        "仅支持分享页直接公开非加密媒体的单视频；"
        "平台未公开媒体时请上传自己拥有或已获授权的文件。"
    )


@pytest.mark.asyncio
async def test_failures_outside_the_recent_decision_window_do_not_degrade() -> None:
    service = ProviderStatusService(
        Reader(
            (
                *(result(index) for index in range(5)),
                result(6, error="inspection_timeout"),
                result(7, error="extractor_regression"),
            )
        ),
        (baseline(),),
        now=lambda: NOW,
    )

    assert (await service.list())[0].status is ProviderSupportStatus.UNKNOWN


@pytest.mark.asyncio
async def test_two_transient_failures_degrade_without_leaking_details() -> None:
    service = ProviderStatusService(
        Reader(
            (
                result(0, error="inspection_timeout"),
                result(1, error="extractor_regression"),
            )
        ),
        (baseline(),),
        now=lambda: NOW,
    )

    view = (await service.list())[0]

    assert view.status is ProviderSupportStatus.DEGRADED
    assert view.user_action == "平台当前不稳定，请稍后重试。"


@pytest.mark.asyncio
async def test_stale_failures_do_not_override_release_verification() -> None:
    service = ProviderStatusService(
        Reader(
            (
                result(27 * 60, error="inspection_timeout"),
                result(28 * 60, error="extractor_regression"),
            )
        ),
        (baseline(ProviderSupportStatus.VERIFIED),),
        now=lambda: NOW,
    )

    view = (await service.list())[0]

    assert view.status is ProviderSupportStatus.VERIFIED
    assert view.download_available is False


@pytest.mark.asyncio
async def test_stale_media_route_is_not_ready_after_analysis_success() -> None:
    service = ProviderStatusService(
        Reader(
            (
                result(0, stage=ProviderCanaryStage.ANALYSIS),
                result(27 * 60, stage=ProviderCanaryStage.MEDIA),
            )
        ),
        (baseline(ProviderSupportStatus.VERIFIED),),
        now=lambda: NOW,
    )

    view = (await service.list())[0]

    assert view.last_verified_at == NOW
    assert view.download_available is False
    assert view.access_state is ProviderAccessState.PUBLIC_PROBE


@pytest.mark.asyncio
async def test_runtime_revision_change_does_not_reuse_old_media_success() -> None:
    new_context = replace(access_context(), runtime_revision="b" * 64)
    service = ProviderStatusService(
        Reader((result(0, stage=ProviderCanaryStage.MEDIA),)),
        (baseline(ProviderSupportStatus.VERIFIED),),
        now=lambda: NOW,
        context_reader=ContextReader((new_context,)),
    )

    view = (await service.list())[0]

    assert view.download_available is False
    assert view.last_media_verified_at is None
    assert view.access_state is ProviderAccessState.PUBLIC_PROBE


@pytest.mark.asyncio
async def test_admin_catalog_controls_public_order_names_and_custom_entries() -> None:
    service = ProviderStatusService(
        Reader(()),
        (baseline(),),
        now=lambda: NOW,
        catalog=Catalog(),  # type: ignore[arg-type]
    )

    views = await service.list()

    assert [item.key for item in views] == ["custom", "vimeo"]
    assert views[0].status is ProviderSupportStatus.UNSUPPORTED
    assert views[0].registered is False
    assert views[1].display_name == "Vimeo 视频"


@pytest.mark.asyncio
async def test_live_operator_session_without_evidence_is_unverified_not_login() -> None:
    operator = replace(
        baseline(ProviderSupportStatus.ACCESS_REQUIRED),
        access_modes=(ProviderAccessMode.OPERATOR_MANAGED,),
    )
    service = ProviderStatusService(
        Reader(()),
        (operator,),
        now=lambda: NOW,
        context_reader=ContextReader(
            (access_context(access_mode=ProviderAccessMode.OPERATOR_MANAGED),)
        ),
    )

    view = (await service.list())[0]

    assert view.status is ProviderSupportStatus.UNKNOWN
    assert view.access_state is ProviderAccessState.OPERATOR_PROBE
    assert view.user_action == "该平台尚未完成当前版本的真实下载验证。"


@pytest.mark.asyncio
async def test_missing_operator_session_still_requires_authorization() -> None:
    operator = replace(
        baseline(ProviderSupportStatus.ACCESS_REQUIRED),
        access_modes=(ProviderAccessMode.OPERATOR_MANAGED,),
    )
    service = ProviderStatusService(
        Reader(()),
        (operator,),
        now=lambda: NOW,
        context_reader=ContextReader(()),
    )

    view = (await service.list())[0]

    assert view.access_state is ProviderAccessState.AUTHORIZATION_REQUIRED
