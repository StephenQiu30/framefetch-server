from dataclasses import replace
from hashlib import sha256

import pytest
from app.services.provider_types import ProviderAccessContextRef, ProviderAccessMode
from app.workers.runner.contracts import ProviderAccessContextContract


def test_legacy_context_keeps_its_persisted_shape_and_generation() -> None:
    document = {
        "provider_key": "generic",
        "profile_version": "default",
        "access_mode": "anonymous",
        "credential_version_id": None,
        "egress_affinity_id": "default",
        "client_profile_id": "yt-dlp-default",
        "attestation_provider_version": None,
        "engine_commit": "pinned",
    }
    context = ProviderAccessContextRef.from_document(document)
    old_identity = "\x1f".join(
        (
            "generic",
            "default",
            "anonymous",
            "",
            "default",
            "yt-dlp-default",
            "",
            "pinned",
        )
    )

    assert context.runtime_revision == "legacy"
    assert context.to_document() == document
    assert context.generation_id == sha256(old_identity.encode()).hexdigest()

    current = replace(context, runtime_revision="a" * 64)
    assert current.to_document()["runtime_revision"] == "a" * 64
    assert current.generation_id != context.generation_id


def current_context() -> ProviderAccessContextRef:
    return ProviderAccessContextRef(
        provider_key="example",
        profile_version="public",
        access_mode=ProviderAccessMode.ANONYMOUS,
        credential_version_id=None,
        egress_affinity_id="logical-egress",
        client_profile_id="client",
        attestation_provider_version=None,
        engine_commit="engine",
        runtime_revision="a" * 64,
        strategy_id="yt-dlp-anonymous",
        adapter_revision="adapter-1",
        protocol_capabilities=("http-media",),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("strategy_id", "browser-page"),
        ("adapter_revision", "adapter-2"),
        ("browser_context_revision", "browser-2"),
        ("protocol_capabilities", ("http-media", "sabr")),
        ("egress_observation_ref", "observation-2"),
    ],
)
def test_behavior_changes_invalidate_frozen_context(field, value):
    context = current_context()
    changed = replace(context, **{field: value})
    assert changed.generation_id != context.generation_id
    assert ProviderAccessContextRef.from_document(changed.to_document()) == changed
    assert ProviderAccessContextContract.from_domain(changed).to_domain() == changed


def test_session_source_changes_invalidate_frozen_context():
    context = replace(
        current_context(),
        access_mode=ProviderAccessMode.OPERATOR_MANAGED,
        credential_version_id="session:1",
        session_source_id="chrome_source:example",
    )
    assert (
        replace(context, session_source_id="managed_browser:example").generation_id
        != context.generation_id
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"adapter_revision": None},
        {"runtime_revision": "legacy"},
        {"session_source_id": "chrome_source:account"},
        {"protocol_capabilities": ("http-media", "http-media")},
    ],
)
def test_context_rejects_incomplete_or_ambiguous_strategy_binding(changes):
    with pytest.raises(ValueError):
        replace(current_context(), **changes)


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_source_id", "chrome_source:account"),
        ("browser_context_revision", "browser-2"),
        ("egress_observation_ref", "observation-2"),
    ],
)
def test_contract_cannot_hide_context_facts_without_a_strategy(field, value):
    document = current_context().to_document()
    document.update(strategy_id=None, adapter_revision=None, protocol_capabilities=[])
    document[field] = value
    with pytest.raises(ValueError):
        ProviderAccessContextContract.model_validate(document)
