"""Resolve t.cn before a generic redirect reaches the visitor HTML page."""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import urljoin, urlsplit

import httpx
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_normalizers import weibo_url
from yt_dlp.extractor.common import InfoExtractor  # type: ignore[import-untyped]
from yt_dlp.extractor.weibo import WeiboIE, WeiboVideoIE  # type: ignore[import-untyped]
from yt_dlp.utils import ExtractorError  # type: ignore[import-untyped]


class WeiboOfficialShortIE(InfoExtractor):  # type: ignore[misc]
    IE_NAME = "WeiboOfficialShort"
    _VALID_URL = r"https?://t\.cn/(?P<id>[A-Za-z0-9]+)/?(?:[?#]|$)"

    def _real_extract(self, url: str) -> dict[str, Any]:
        share_id = self._match_id(url)
        proxy = self.get_param("proxy")
        if not isinstance(proxy, str) or not proxy:
            raise _failure("provider_temporarily_unavailable", share_id)
        try:
            current = weibo_url(url, urlsplit(url))
            with httpx.Client(
                proxy=proxy, trust_env=False, follow_redirects=False, timeout=5.0
            ) as client:
                for _ in range(3):
                    # Read headers only: do not follow a landing page to its
                    # visitor login page or download arbitrary redirect bodies.
                    with client.stream("GET", current) as response:
                        if response.status_code == 429:
                            raise _failure("provider_rate_limited", share_id)
                        if response.status_code >= 500:
                            raise _failure("provider_temporarily_unavailable", share_id)
                        location = response.headers.get("location")
                        if (
                            response.status_code not in {301, 302, 303, 307, 308}
                            or not location
                        ):
                            raise _failure("provider_link_unavailable", share_id)
                        target = urljoin(current, location)
                        current = weibo_url(target, urlsplit(target))
                    if WeiboVideoIE.suitable(current):
                        return cast(
                            dict[str, Any],
                            self.url_result(current, ie=WeiboVideoIE.ie_key()),
                        )
                    if WeiboIE.suitable(current):
                        return cast(
                            dict[str, Any],
                            self.url_result(current, ie=WeiboIE.ie_key()),
                        )
        except (RunnerFailure, ValueError, httpx.RemoteProtocolError) as exc:
            raise _failure("provider_link_unavailable", share_id) from exc
        except httpx.HTTPError as exc:
            raise _failure("provider_temporarily_unavailable", share_id) from exc
        raise _failure("provider_link_unavailable", share_id)


def _failure(code: str, share_id: str) -> ExtractorError:
    return ExtractorError(f"Framefetch {code}", video_id=share_id, expected=True)
