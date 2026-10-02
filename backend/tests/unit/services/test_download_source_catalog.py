from app.services.downloads.source_catalog import (
    DOWNLOAD_SOURCES,
    download_source,
)
from app.services.provider_types import ProviderKey


def test_dailymotion_has_a_public_download_reporting_category() -> None:
    source = download_source(ProviderKey.DAILYMOTION)
    assert source.key == "dailymotion"
    assert source.name == "Dailymotion"
    assert source.extractor_prefixes == ("dailymotion",)
    assert source in DOWNLOAD_SOURCES
    assert len({item.key for item in DOWNLOAD_SOURCES}) == len(DOWNLOAD_SOURCES)
