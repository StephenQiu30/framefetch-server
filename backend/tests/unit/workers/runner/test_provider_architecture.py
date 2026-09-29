from __future__ import annotations

from dataclasses import replace
from urllib.parse import SplitResult

import pytest
from app.integrations.provider_status import configured_provider_statuses
from app.integrations.site_session_catalog import (
    SiteSessionRoutes,
    known_session_provider_keys,
    site_target_for_url,
)
from app.services.downloads.errors import MediaInspectionPolicyNotAllowed
from app.services.provider_access import ProviderAccessPolicy as Policy
from app.services.provider_types import ProviderSupportStatus
from app.services.site_sessions import SessionEntitlement, SiteSessionPolicy
from app.workers.runner import provider_registry
from app.workers.runner.provider_errors import FailureRule, ProviderFailureContext
from app.workers.runner.provider_factories import standard_provider
from app.workers.runner.provider_registry import (
    ProviderRegistry,
    default_provider_registry,
)


def test_one_profile_defines_a_complete_builtin_extractor_integration() -> None:
    calls: list[str] = []

    def canonical_url(url: str, parsed: SplitResult) -> str:
        calls.append(url)
        return parsed._replace(query="", fragment="").geturl()

    profile = standard_provider(
        "example",
        "Example Video",
        ("video.example",),
        version="example",
        normalize_url=canonical_url,
        command_args=("--impersonate", "Chrome-136:Macos-15"),
        canary_suite="example-public-video",
    )
    request = ProviderRegistry((profile,)).prepare(
        "https://video.example/watch/123?tracking=1#player"
    )

    assert request.profile is profile
    assert request.request_url == "https://video.example/watch/123"
    assert request.profile.command_args == (
        "--impersonate",
        "Chrome-136:Macos-15",
    )
    assert calls == [request.source_url]


def test_registry_rejects_duplicate_provider_keys_before_startup() -> None:
    first = standard_provider("duplicate", "First", ("first.example",))
    second = standard_provider("duplicate", "Second", ("second.example",))

    with pytest.raises(ValueError, match="provider key is registered twice"):
        ProviderRegistry((first, second))


def test_failure_rules_are_orderable_provider_strategies() -> None:
    rule = FailureRule(
        "extractor_regression",
        502,
        any_stderr=(b"schema changed",),
        providers=frozenset({"example"}),
    )

    assert rule.matches(
        ProviderFailureContext("example", "https://video.example/1", False),
        b"error: schema changed",
    )
    assert not rule.matches(
        ProviderFailureContext("other", "https://other.example/1", False),
        b"error: schema changed",
    )


@pytest.mark.parametrize("policy", [Policy.PUBLIC, Policy.OPERATOR_PUBLIC])
async def test_one_declaration_drives_route_status_and_session_catalog(
    monkeypatch: pytest.MonkeyPatch, policy: Policy
) -> None:
    account = policy is Policy.OPERATOR_PUBLIC
    profile = standard_provider(
        "example",
        "Example",
        ("media.example.com",),
        access_policy=policy,
        operator_cookie_domains=frozenset({"example.com"}) if account else frozenset(),
        session_policy=(
            SiteSessionPolicy("example.com", "example", "https://example.com/login")
            if account
            else None
        ),
    )
    registry = ProviderRegistry((profile,))
    monkeypatch.setattr(provider_registry, "_ACTIVE_PROVIDER_REGISTRY", registry)
    url = "https://media.example.com/video/1"

    assert await SiteSessionRoutes().policy_for(url) is policy
    await SiteSessionRoutes().ensure_ready(url)
    status = configured_provider_statuses(frozenset({"example"}))[0]
    assert status.default_access_policy_id is policy
    assert status.access_modes == (policy.access_mode,)
    assert registry.keys_for_policy(policy) == frozenset({"example"})
    assert known_session_provider_keys() == (
        frozenset({"example"}) if account else frozenset()
    )
    if account:
        target = site_target_for_url(url)
        assert target.policy is profile.session_policy
        assert target.cookie_domains == frozenset({"example.com"})


def test_all_23_execution_policies_preserve_approved_scope() -> None:
    profiles = default_provider_registry().profiles
    assert len(profiles) == 23
    assert {p.key for p in profiles if p.access_policy is Policy.PUBLIC} == {
        "bilibili",
        "tiktok",
        "kuaishou",
        "vimeo",
        "twitch",
        "weibo",
        "snapchat",
        "linkedin",
        "telegram",
        "kick",
        "tumblr",
        "hongguo_web",
    }
    assert {p.key for p in profiles if p.access_policy is Policy.PERSONAL_ENTITLED} == {
        "youku",
        "qqvideo",
    }
    assert {p.key for p in profiles if p.access_policy is Policy.OPERATOR_PUBLIC} == {
        "youtube",
        "douyin",
        "xiaohongshu",
        "wechat_channels",
        "x",
        "instagram",
        "facebook",
        "reddit",
        "pinterest",
    }


def test_registry_rejects_engine_and_execution_policy_conflicts() -> None:
    public = standard_provider("example", "Example", ("example.com",))
    for policy in (Policy.OPERATOR_PUBLIC, Policy.PUBLIC_SESSION):
        with pytest.raises(ValueError, match="invalid access policy"):
            ProviderRegistry((replace(public, access_policy=policy),))


def test_registry_rejects_incomplete_or_conflicting_account_declarations() -> None:
    profile = standard_provider(
        "example",
        "Example",
        ("example.com",),
        access_policy=Policy.OPERATOR_PUBLIC,
        operator_cookie_domains=frozenset({"example.com"}),
    )
    with pytest.raises(ValueError, match="missing session policy"):
        ProviderRegistry((profile,))
    session = SiteSessionPolicy("example.com", "other", "https://example.com/login")
    with pytest.raises(ValueError, match="mismatched session"):
        ProviderRegistry((replace(profile, session_policy=session),))
    personal = replace(
        session,
        provider_key="example",
        entitlement=SessionEntitlement.ACCOUNT_ENTITLED_FULL_VIDEO,
    )
    with pytest.raises(ValueError, match="mismatched entitlement"):
        ProviderRegistry((replace(profile, session_policy=personal),))


async def test_disabled_profile_cannot_be_selected_or_advertised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = standard_provider(
        "example",
        "Example",
        ("example.com",),
        status=ProviderSupportStatus.DISABLED,
    )
    registry = ProviderRegistry((profile,))
    monkeypatch.setattr(provider_registry, "_ACTIVE_PROVIDER_REGISTRY", registry)
    assert registry.keys_for_policy(Policy.PUBLIC) == frozenset()
    assert configured_provider_statuses()[0].access_modes == ()
    with pytest.raises(MediaInspectionPolicyNotAllowed):
        await SiteSessionRoutes().policy_for("https://example.com/video/1")


async def test_approved_peertube_uses_its_declared_public_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers.runner.provider_catalog_incremental import peertube_profile

    registry = ProviderRegistry((peertube_profile(frozenset({"video.example.com"})),))
    monkeypatch.setattr(provider_registry, "_ACTIVE_PROVIDER_REGISTRY", registry)
    assert (
        await SiteSessionRoutes().policy_for(
            "https://video.example.com/w/AbCdEfGhIjKlMnOpQrStUv"
        )
        is Policy.PUBLIC
    )
    with pytest.raises(MediaInspectionPolicyNotAllowed):
        await SiteSessionRoutes().policy_for(
            "https://unapproved.example.com/w/AbCdEfGhIjKlMnOpQrStUv"
        )
