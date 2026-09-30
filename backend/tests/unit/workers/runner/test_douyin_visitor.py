from __future__ import annotations

from app.workers.runner.plugins.yt_dlp_plugins.extractor._douyin_visitor import (
    ensure_visitor_cookies,
)


class FakeExtractor:
    def __init__(self, cookies: dict[str, object]) -> None:
        self.cookies = cookies
        self.requests: list[tuple[str, dict[str, object]]] = []

    def _get_cookies(self, url: str) -> dict[str, object]:
        assert url == "https://www.douyin.com/"
        return self.cookies

    def _request_webpage(self, url: str, video_id: str, **kwargs: object) -> None:
        assert video_id == "123"
        self.requests.append((url, kwargs))


def test_initializes_visitor_session_on_first_party_pages() -> None:
    extractor = FakeExtractor({})

    ensure_visitor_cookies(extractor, "123")  # type: ignore[arg-type]

    assert [url for url, _ in extractor.requests] == [
        "https://www.iesdouyin.com/",
        "https://www.douyin.com/",
    ]
    # A failed warm-up must fall through to the normal extraction errors.
    assert all(kwargs["fatal"] is False for _, kwargs in extractor.requests)


def test_reuses_an_existing_visitor_or_account_session() -> None:
    extractor = FakeExtractor({"ttwid": object()})

    ensure_visitor_cookies(extractor, "123")  # type: ignore[arg-type]

    assert extractor.requests == []
