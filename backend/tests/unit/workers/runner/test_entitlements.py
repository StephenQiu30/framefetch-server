from __future__ import annotations

import pytest
from app.workers.runner.entitlements import enforce_media_rights
from app.workers.runner.errors import RunnerFailure


@pytest.mark.parametrize(
    "provider",
    (
        "douyin",
        "xiaohongshu",
        "reddit",
        "x",
        "instagram",
        "facebook",
        "pinterest",
        "wechat_channels",
    ),
)
def test_anonymous_allows_unrestricted_public_web_metadata(provider: str) -> None:
    enforce_media_rights(
        {"id": "123", "formats": [{"has_drm": None}]},
        provider_key=provider,
    )


@pytest.mark.parametrize("provider", ("tiktok", "vimeo", "generic"))
def test_anonymous_processing_checks_content_restrictions(
    provider: str,
) -> None:
    enforce_media_rights(
        {"availability": "public"},
        provider_key=provider,
    )
    with pytest.raises(RunnerFailure) as caught:
        enforce_media_rights(
            {"availability": "private"},
            provider_key=provider,
        )
    assert caught.value.code == "content_unavailable"


@pytest.mark.parametrize(
    "payload",
    (
        {"availability": "premium_only"},
        {"availability": "subscriber_only"},
        {"availability": "paid"},
        {"is_premium": True},
        {"is_member_only": True},
    ),
)
def test_anonymous_rejects_personal_entitlement_markers(
    payload: dict[str, object],
) -> None:
    with pytest.raises(RunnerFailure) as caught:
        enforce_media_rights(
            payload,
            provider_key="qqvideo",
        )

    assert caught.value.code == "content_unavailable"


@pytest.mark.parametrize(
    "payload",
    (
        {"is_private": True},
        {"is_premium": True},
        {"is_member_only": True},
        {"is_preview": True},
        {"requires_purchase": True},
        {"availability": "vip_only"},
        {"availability": "purchase_required"},
    ),
)
def test_anonymous_access_rejects_restricted_metadata(
    payload: dict[str, object],
) -> None:
    with pytest.raises(RunnerFailure) as caught:
        enforce_media_rights(
            payload,
            provider_key="qqvideo",
        )

    assert caught.value.code == "content_unavailable"


@pytest.mark.parametrize(
    "restriction,code",
    [
        ({"is_private": True}, "content_unavailable"),
        ({"has_drm": True}, "content_protected"),
    ],
)
def test_collection_checks_each_member(restriction: dict, code: str) -> None:
    with pytest.raises(RunnerFailure) as caught:
        enforce_media_rights(
            {"availability": "public", "entries": [{"id": "first"}, restriction]},
            provider_key="instagram",
        )
    assert caught.value.code == code


def test_missing_login_is_classified_as_login_required():
    with pytest.raises(RunnerFailure) as caught:
        enforce_media_rights({"availability": "needs_auth"}, provider_key="youtube")
    assert caught.value.code == "login_required"
    assert caught.value.failure.failure_class.value == "login_required"
