"""Offline article HTML from validated, canonical reader Markdown."""

from markdown_it import MarkdownIt


def render_content_html(markdown: str, *, language: str = "zh-CN") -> bytes:
    if language not in {"zh-CN", "en-US"}:
        raise ValueError("unsupported document language")
    if not markdown.strip() or len(markdown.encode()) > 1_000_000:
        raise ValueError("content HTML is empty or exceeds its budget")
    body = MarkdownIt("commonmark", {"html": False, "linkify": False}).render(markdown)
    # No remote fonts, images, scripts, tracking or editor metadata.
    document = (
        f'<!doctype html><html lang="{language}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'\">"
        "<title>文章正文</title></head><body>"
        '<main style="max-width:720px;margin:24px auto;padding:0 20px;'
        "font:17px/1.9 -apple-system,BlinkMacSystemFont,sans-serif;"
        'color:#222;overflow-wrap:anywhere">'
        f"{body}</main></body></html>"
    )
    return document.encode("utf-8")
