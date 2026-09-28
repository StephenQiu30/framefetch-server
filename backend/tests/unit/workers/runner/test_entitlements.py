from __future__ import annotations

import pytest
from app.services.provider_types import ProviderAccessMode
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
def test_operator_allows_unrestricted_public_web_metadata(provider: str) -> None:
    enforce_media_rights(
        {"id": "123", "formats": [{"has_drm": None}]},
        provider_key=provider,
        access_mode=ProviderAccessMode.OPERATOR_MANAGED,
    )


@pytest.mark.parametrize("provider", ("tiktok", "vimeo", "generic"))
def test_any_imported_site_session_may_process_clear_public_media(
    provider: str,
) -> None:
    # The broker admits a site; entitlement rules still apply per media item.
    enforce_media_rights(
        {"availability": "public"},
        provider_key=provider,
        access_mode=ProviderAccessMode.OPERATOR_MANAGED,
    )
    with pytest.raises(RunnerFailure) as caught:
        enforce_media_rights(
            {"availability": "private"},
            provider_key=provider,
            access_mode=ProviderAccessMode.OPERATOR_MANAGED,
        )
    assert caught.value.code == "content_private"


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
def test_operator_entitlement_drift_disables_personal_account(
    payload: dict[str, object],
) -> None:
    with pytest.raises(RunnerFailure) as caught:
        enforce_media_rights(
            payload,
            provider_key="qqvideo",
            access_mode=ProviderAccessMode.OPERATOR_MANAGED,
        )

    assert caught.value.code == "credential_entitlement_drift"


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
            access_mode=ProviderAccessMode.ANONYMOUS,
        )

    assert caught.value.code in {"content_private", "content_not_entitled"}


@pytest.mark.parametrize(
    "restriction,code",
    [
        ({"is_private": True}, "content_private"),
        ({"has_drm": True}, "drm_protected"),
    ],
)
def test_collection_checks_each_member(restriction: dict, code: str) -> None:
    with pytest.raises(RunnerFailure) as caught:
        enforce_media_rights(
            {"availability": "public", "entries": [{"id": "first"}, restriction]},
            provider_key="instagram",
            access_mode=ProviderAccessMode.ANONYMOUS,
        )
    assert caught.value.code == code
