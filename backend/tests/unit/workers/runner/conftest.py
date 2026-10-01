"""Synthetic named extractor for Runner tests using media.example.com fixtures."""

from urllib.parse import urlsplit

import pytest
from yt_dlp import extractor as yt_dlp_extractor


@pytest.fixture(autouse=True)
def controlled_named_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    from uuid import UUID

    monkeypatch.setattr("app.workers.runner.main.uuid4", lambda: UUID(int=0))
    original = yt_dlp_extractor.get_info_extractor

    class ControlledExtractor:
        @staticmethod
        def suitable(url: str) -> bool:
            return urlsplit(url).hostname == "media.example.com"

    def get_extractor(key: str):
        return ControlledExtractor if key == "Controlled" else original(key)

    monkeypatch.setattr(yt_dlp_extractor, "get_info_extractor", get_extractor)


@pytest.fixture(autouse=True)
def no_external_ip_echo_in_runner_unit_tests(monkeypatch):
    async def observed(binding, *, settings):
        return binding

    monkeypatch.setattr("app.workers.runner.service.observe_egress", observed)
