from __future__ import annotations

from urllib.parse import SplitResult

import pytest
from app.workers.runner.provider_errors import FailureRule, ProviderFailureContext
from app.workers.runner.provider_factories import standard_provider
from app.workers.runner.provider_registry import (
    ProviderRegistry,
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
