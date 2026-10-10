"""Guard paid Bilibili metadata before upstream turns preview streams into formats."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.workers.runner.url_policy import UrlPolicyError, validate_media_url
from yt_dlp.extractor.bilibili import BiliBiliIE  # type: ignore[import-untyped]

from ._content_access import (
    enforce_bilibili_access,
    enforce_bilibili_playinfo,
)


class _BiliBiliAccessIE(BiliBiliIE, plugin_name="content_access"):  # type: ignore[misc, call-arg]
    def _search_json(
        self,
        start_pattern: str,
        string: str,
        name: str,
        video_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        result = super()._search_json(
            start_pattern, string, name, video_id, *args, **kwargs
        )
        if name == "initial state" and isinstance(result, dict):
            for key in ("videoData", "videoInfo"):
                video = result.get(key)
                if isinstance(video, dict):
                    enforce_bilibili_access(video)
        if name == "play info" and isinstance(result, dict):
            data = result.get("data")
            if isinstance(data, dict):
                enforce_bilibili_playinfo(data)
        return result

    def extract_formats(self, play_info: Any) -> Any:
        if isinstance(play_info, dict):
            enforce_bilibili_playinfo(play_info)
            play_info = _prefer_admitted_urls(play_info)
        return super().extract_formats(play_info)


def _prefer_admitted_urls(play_info: dict[str, Any]) -> dict[str, Any]:
    """Use an official backup rendition when the primary violates URL policy.

    Bilibili may put a non-standard-port PCDN URL first. yt-dlp drops the
    backup URLs, so select before that loss; never rewrite the URL or relax
    the runner's network policy. Every backup still belongs to this rendition.
    """
    result = deepcopy(play_info)

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            keys = [key for key in ("baseUrl", "base_url", "url") if key in value]
            if keys:
                urls = [value[key] for key in keys]
                for key in ("backupUrl", "backup_url"):
                    backup = value.get(key)
                    if isinstance(backup, list):
                        urls.extend(backup)
                for url in urls:
                    if not isinstance(url, str):
                        continue
                    try:
                        validate_media_url(url)
                    except UrlPolicyError:
                        continue
                    for key in keys:
                        value[key] = url
                    break
            for child in value.values():
                if isinstance(child, (dict, list)):
                    visit(child)

    visit(result)
    return result
