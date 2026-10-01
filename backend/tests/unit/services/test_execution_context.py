from dataclasses import replace

import pytest
from app.services.provider_types import ExecutionContext


def context() -> ExecutionContext:
    return ExecutionContext(
        provider_key="bilibili",
        registry_revision="registry-fixture",
        resolved_layer="L1",
        client="yt-dlp-default",
        engine_revision="engine-fixture",
        egress_route="cn",
        egress_revision="egress-fixture",
        egress_class="unknown",
        egress_observed_ip=None,
        identity_used=False,
        identity_digest=None,
        browser_context_kind="none",
    )


def test_execution_context_roundtrip_has_exactly_the_twelve_design_fields():
    value = context()
    document = value.to_document()
    assert set(document) == {
        "provider_key",
        "registry_revision",
        "resolved_layer",
        "client",
        "engine_revision",
        "egress_route",
        "egress_revision",
        "egress_class",
        "egress_observed_ip",
        "identity_used",
        "identity_digest",
        "browser_context_kind",
    }
    assert ExecutionContext.from_document(document) == value
    for changed in (
        {**document, "strategy_id": "old"},
        {**document, "cookies": "sensitive"},
        {k: v for k, v in document.items() if k != "registry_revision"},
        {
            "provider_key": "bilibili",
            "resolved_layer": "L1",
            "egress_route": "cn",
            "client_profile": "yt-dlp-default",
            "identity_used": False,
            "engine_version": "fixture",
        },
    ):
        with pytest.raises(ValueError):
            ExecutionContext.from_document(changed)


@pytest.mark.parametrize(
    "changes",
    [
        {"provider_key": None},
        {"registry_revision": "bad value"},
        {"resolved_layer": "L4"},
        {"client": ""},
        {"engine_revision": "contains/url"},
        {"egress_revision": "secret=value"},
        {"egress_class": "untrusted"},
        {"egress_observed_ip": "not-an-ip"},
        {"egress_observed_ip": "127.1"},
        {"egress_observed_ip": "127.00.0.1"},
        {"egress_observed_ip": "127.0.0.1/32"},
        {"egress_observed_ip": "fe80::1%en0"},
        {"identity_used": 1},
        {"identity_digest": "present-without-identity"},
        {"identity_used": True},
        {"browser_context_kind": "persistent"},
        {"browser_context_kind": "authenticated"},
        {"browser_context_kind": "anonymous"},
    ],
)
def test_execution_context_rejects_invalid_facts(changes):
    with pytest.raises(ValueError):
        ExecutionContext.from_document({**context().to_document(), **changes})


@pytest.mark.parametrize("ip", ["192.0.2.1", "2001:db8::1", "::ffff:192.0.2.1"])
def test_execution_context_keeps_valid_observed_ip(ip):
    value = replace(context(), egress_observed_ip=ip, egress_class="residential")
    assert ExecutionContext.from_document(value.to_document()) == value


def test_authenticated_browser_context_requires_matching_identity():
    value = replace(
        context(),
        resolved_layer="L3",
        browser_context_kind="authenticated",
        identity_used=True,
        identity_digest="identity-fixture",
    )
    assert ExecutionContext.from_document(value.to_document()) == value
    anonymous = replace(
        context(), resolved_layer="L3", browser_context_kind="anonymous"
    )
    assert ExecutionContext.from_document(anonymous.to_document()) == anonymous
