"""Pure account transport validation using only synthetic credentials."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from app.workers.identity.yuanbao_account import (
    YUANBAO_ORIGIN,
    YuanbaoAccountMaterial,
    stable_yuanbao_account_digest,
    validate_yuanbao_account_material,
    validate_yuanbao_account_payload,
)
from pydantic import SecretStr, ValidationError

ACCOUNT = "synthetic-account-only"
AUTH = "synthetic-auth-only"
KEY = "synthetic-digest-key-only"


def account_payload():
    return {"origin": YUANBAO_ORIGIN, "account_id": ACCOUNT, "auth_token": AUTH}


def material_payload(end):
    account = validate_yuanbao_account_payload(account_payload())
    return {
        **account_payload(),
        "kind": "yuanbao_account",
        "digest": stable_yuanbao_account_digest(
            account, site="wechat_channels", key=KEY
        ),
        "local_use_deadline": end,
    }


def test_account_fields_are_secret_frozen_and_not_printed():
    account = validate_yuanbao_account_payload(account_payload())
    assert isinstance(account.account_id, SecretStr)
    assert account.auth_token.get_secret_value() == AUTH
    assert ACCOUNT not in repr(account) and AUTH not in str(account)
    with pytest.raises(ValidationError):
        account.auth_token = SecretStr("synthetic-other")


@pytest.mark.parametrize(
    "change",
    [
        {"origin": "https://other.invalid"},
        {"origin": "https://yuanbao.tencent.com/"},
        {"account_id": 123},
        {"account_id": ""},
        {"account_id": " synthetic "},
        {"account_id": "synthetic\x00account"},
        {"account_id": "界" * 342},
        {"auth_token": b"synthetic"},
        {"auth_token": "synthetic\r\nvalue"},
        {"auth_token": "界" * 2731},
        {"headers": {"X-Token": AUTH}},
        {"cookies": []},
        {"user_agent": "synthetic-user-agent"},
    ],
)
def test_payload_rejects_unsafe_fields_without_error_value_leaks(change):
    with pytest.raises(ValidationError) as error:
        validate_yuanbao_account_payload({**account_payload(), **change})
    assert AUTH not in str(error.value) and ACCOUNT not in str(error.value)


def test_utf8_limits_accept_the_exact_byte_boundaries():
    account = validate_yuanbao_account_payload(
        {"origin": YUANBAO_ORIGIN, "account_id": "é" * 512, "auth_token": "a" * 8192}
    )
    assert len(account.account_id.get_secret_value().encode()) == 1024


def test_digest_binds_account_and_key_but_excludes_operation_fields():
    now = datetime.now(UTC)
    first = YuanbaoAccountMaterial.model_validate(
        material_payload(now + timedelta(seconds=10))
    )
    second = first.model_copy(
        update={"local_use_deadline": now + timedelta(seconds=20)}
    )
    digest = stable_yuanbao_account_digest(first, site="wechat_channels", key=KEY)
    assert digest == stable_yuanbao_account_digest(
        second, site="wechat_channels", key=KEY
    )
    assert digest != stable_yuanbao_account_digest(
        first, site="wechat_channels", key=KEY + "other"
    )
    for field in ("account_id", "auth_token"):
        changed = validate_yuanbao_account_payload(
            {**account_payload(), field: "synthetic-different"}
        )
        assert digest != stable_yuanbao_account_digest(
            changed, site="wechat_channels", key=KEY
        )
    with pytest.raises(ValueError, match="invalid account digest context"):
        stable_yuanbao_account_digest(first, site="instagram", key=KEY)


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "cookies"},
        {"digest": "A" * 64},
        {"digest": "a" * 63},
        {"local_use_deadline": 1_900_000_000},
        {"local_use_deadline": "1900000000"},
        {"local_use_deadline": datetime(2030, 1, 1)},
        {
            "local_use_deadline": datetime(
                2030, 1, 1, tzinfo=timezone(timedelta(hours=8))
            )
        },
    ],
)
def test_material_requires_fixed_kind_digest_and_utc_cap(change):
    now = datetime.now(UTC)
    with pytest.raises(ValueError):
        validate_yuanbao_account_material(
            {**material_payload(now + timedelta(seconds=10)), **change},
            deadline=now + timedelta(seconds=20),
            now=now,
        )


@pytest.mark.parametrize("offset", [0, -1, 21])
def test_material_cap_must_be_future_and_within_operation(offset):
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="invalid account use deadline"):
        validate_yuanbao_account_material(
            material_payload(now + timedelta(seconds=offset)),
            deadline=now + timedelta(seconds=20),
            now=now,
        )


def test_utc_json_cap_is_validated_without_claiming_token_expiry():
    now = datetime.now(UTC)
    end = now + timedelta(seconds=10)
    material = validate_yuanbao_account_material(
        material_payload(end.isoformat()), deadline=end, now=now
    )
    assert material.local_use_deadline == end
    assert not hasattr(material, "token_expires_at")
