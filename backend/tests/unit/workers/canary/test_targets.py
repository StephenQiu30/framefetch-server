import pytest
from app.services.provider_types import ProviderAccessMode, ProviderCanaryStage
from app.workers.canary.targets import (
    parse_canary_targets,
    validate_canary_target_routes,
)
from pydantic import SecretStr


def test_parses_authorized_https_targets_without_exposing_urls() -> None:
    targets = parse_canary_targets(
        SecretStr(
            '[{"target_id":"youtube-owned-1","provider_key":"youtube",'
            '"stage":"metadata","access_mode":"operator_managed",'
            '"url":"https://youtube.com/watch?v=owned"},'
            '{"target_id":"youtube-owned-1","provider_key":"youtube",'
            '"stage":"media","access_mode":"operator_managed",'
            '"url":"https://youtube.com/watch?v=owned"}]'
        )
    )

    assert len(targets) == 2
    assert targets[1].stage is ProviderCanaryStage.MEDIA
    assert targets[1].access_mode is ProviderAccessMode.OPERATOR_MANAGED
    assert "youtube.com" not in repr(targets[0])


def test_rejects_insecure_mismatched_and_duplicate_targets() -> None:
    values = (
        '[{"target_id":"one","provider_key":"vimeo","stage":"metadata",'
        '"access_mode":"anonymous","url":"http://vimeo.com/76979871"}]',
        '[{"target_id":"one","provider_key":"youtube","stage":"metadata",'
        '"access_mode":"anonymous","url":"https://vimeo.com/76979871"}]',
        '[{"target_id":"one","provider_key":"vimeo","stage":"metadata",'
        '"access_mode":"anonymous",'
        '"url":"https://user:pass@vimeo.com/76979871"}]',
        '[{"target_id":"one","provider_key":"acfun","stage":"metadata",'
        '"access_mode":"anonymous","url":"https://www.acfun.cn/v/ac1"}]',
        '[{"target_id":"one","provider_key":"vimeo","stage":"metadata",'
        '"access_mode":"anonymous","url":"https://vimeo.com/76979871"},'
        '{"target_id":"one",'
        '"provider_key":"vimeo","stage":"metadata",'
        '"access_mode":"anonymous","url":"https://vimeo.com/22439234"}]',
        '[{"target_id":"one","provider_key":"vimeo","stage":"analysis",'
        '"access_mode":"anonymous","url":"https://vimeo.com/76979871"}]',
        '[{"target_id":"one","provider_key":"vimeo","stage":"metadata",'
        '"access_mode":"anonymous","url":"https://vimeo.com/76979871"},'
        '{"target_id":"one",'
        '"provider_key":"vimeo","stage":"media",'
        '"access_mode":"anonymous","url":"https://vimeo.com/22439234"}]',
        '[{"target_id":"one","provider_key":"vimeo","stage":"metadata",'
        '"url":"https://vimeo.com/76979871"}]',
        '[{"target_id":"one","provider_key":"tiktok","stage":"metadata",'
        '"access_mode":"operator_managed",'
        '"url":"https://www.tiktok.com/@creator/video/123"}]',
        '[{"target_id":"one","provider_key":"vimeo","stage":"metadata",'
        '"access_mode":"anonymous","url":"https://vimeo.com/76979871"},'
        '{"target_id":"one","provider_key":"vimeo","stage":"media",'
        '"access_mode":"operator_managed",'
        '"url":"https://vimeo.com/76979871"}]',
    )

    for value in values:
        try:
            parse_canary_targets(SecretStr(value))
        except ValueError as exc:
            assert str(exc) == "provider canary targets are invalid"
            assert "vimeo.com" not in str(exc)
        else:
            raise AssertionError("invalid target was accepted")


def test_operator_canary_target_requires_a_matching_runner_endpoint() -> None:
    targets = parse_canary_targets(
        SecretStr(
            '[{"target_id":"youtube-owned","provider_key":"youtube",'
            '"stage":"metadata","access_mode":"operator_managed",'
            '"url":"https://www.youtube.com/watch?v=abc12345678"}]'
        )
    )

    try:
        validate_canary_target_routes(targets, frozenset())
    except ValueError as exc:
        assert str(exc) == (
            "provider canary operator targets require matching runner endpoints: "
            "youtube"
        )
        assert "youtube.com" not in str(exc)
    else:
        raise AssertionError("operator canary target without a runner was accepted")

    validate_canary_target_routes(targets, frozenset({"youtube"}))


@pytest.mark.parametrize("mode", ["anonymous", "guest"])
def test_retired_canary_modes_are_rejected(mode):
    import json

    payload = [
        {
            "target_id": "public",
            "provider_key": "douyin",
            "stage": "metadata",
            "access_mode": mode,
            "url": "https://www.douyin.com/video/7674644830270473609",
        }
    ]
    with pytest.raises(ValueError, match="targets are invalid"):
        parse_canary_targets(SecretStr(json.dumps(payload)))
