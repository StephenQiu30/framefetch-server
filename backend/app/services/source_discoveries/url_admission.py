from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from app.services.public_input import extract_public_url

_ARTICLE_PATH = re.compile(r"/s/[A-Za-z0-9_-]{6,256}")
_QUERY_KEYS = frozenset({"__biz", "mid", "idx", "sn", "chksm", "scene"})
_REQUIRED_QUERY_KEYS = frozenset({"__biz", "mid", "idx", "sn"})
_SELECTION = re.compile(r"video=([0-9a-f]{64})")


def selected_article_source(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    matched = _SELECTION.fullmatch(parsed.fragment)
    if matched is None:
        raise ValueError("article video selection is required")
    article = canonicalize_article_url(urlunsplit(parsed._replace(fragment="")))
    return article, matched.group(1)


def canonicalize_article_url(url: str) -> str:
    url = extract_public_url(url)
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").casefold() != "mp.weixin.qq.com"
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("unsupported article URL")
    if _ARTICLE_PATH.fullmatch(parsed.path):
        if parsed.query:
            raise ValueError("article path URLs cannot contain query parameters")
        return urlunsplit(("https", "mp.weixin.qq.com", parsed.path, "", ""))
    if parsed.path != "/s" or not parsed.query:
        raise ValueError("unsupported article URL")
    try:
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise ValueError("invalid article query") from exc
    if (
        not _REQUIRED_QUERY_KEYS <= set(query)
        or not set(query) <= _QUERY_KEYS
        or any(len(values) != 1 or not values[0].strip() for values in query.values())
    ):
        raise ValueError("invalid article query")
    canonical_query = urlencode(
        [(key, query[key][0]) for key in sorted(query)], doseq=False
    )
    return urlunsplit(("https", "mp.weixin.qq.com", "/s", canonical_query, ""))
