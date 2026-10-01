import pytest
from app.services.provider_failures import FailureClass
from app.workers.runner.engine.browser import tiktok
from app.workers.runner.engine.layers.browser import PARSERS, _expected_id
from app.workers.runner.errors import RunnerFailure


def payload():
    return {
        "__DEFAULT_SCOPE__": {
            "webapp.video-detail": {
                "itemInfo": {
                    "itemStruct": {
                        "id": "6748451240264420610",
                        "desc": "Public clip",
                        "privateItem": False,
                        "author": {"privateAccount": False},
                        "video": {
                            "duration": 12,
                            "width": 576,
                            "height": 1024,
                            "playAddr": "https://cdn.example.org/public.mp4",
                        },
                    }
                }
            }
        }
    }


def test_hydration_duration_identity_and_dispatch():
    work = "6748451240264420610"
    result = tiktok.parse_response(payload(), work)
    assert result.provider_media_id == work and result.duration_seconds == 12
    assert result.client == "tiktok:browser" and result.handoff == "http"
    assert PARSERS["tiktok"] is tiktok
    assert (
        _expected_id(f"https://www.tiktok.com/@author/video/{work}", "tiktok") == work
    )
    with pytest.raises(RunnerFailure):
        tiktok.parse_response(payload(), "another-work")


@pytest.mark.parametrize(
    "flag,kind",
    [
        ("privateItem", FailureClass.CONTENT_UNAVAILABLE),
        ("has_drm", FailureClass.CONTENT_PROTECTED),
        ("requires_purchase", FailureClass.CONTENT_UNAVAILABLE),
    ],
)
def test_private_paid_or_drm_never_returns_media(flag, kind):
    value = payload()
    value["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"]["itemStruct"][
        flag
    ] = True
    with pytest.raises(RunnerFailure) as error:
        tiktok.parse_response(value)
    assert error.value.failure.failure_class is kind


def test_malformed_metadata_is_safe_structural_failure():
    value = payload()
    value["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"]["itemStruct"][
        "video"
    ]["bitrateInfo"] = 2
    with pytest.raises(RunnerFailure) as error:
        tiktok.parse_response(value)
    assert error.value.failure.failure_class is FailureClass.EXTRACTOR_BROKEN


def test_unavailable_status_stops_without_media():
    with pytest.raises(RunnerFailure) as error:
        tiktok.parse_response({"statusCode": 10204})
    assert error.value.failure.failure_class is FailureClass.CONTENT_UNAVAILABLE


def test_missing_public_visibility_does_not_become_positive():
    value = payload()
    item = value["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"]["itemStruct"]
    del item["privateItem"]
    with pytest.raises(RunnerFailure) as error:
        tiktok.parse_response(value)
    assert error.value.failure.failure_class is FailureClass.CONTENT_UNAVAILABLE
