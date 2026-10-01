"""Select one YouTube proof provider in the supervised yt-dlp subprocess.

Upstream providers have no common disable option. Restrict their registry after
loading the pinned plugins, before YoutubeDL constructs any extractor. WPC owns
its nodriver browser; Runner owns the subprocess group and private tmpfs.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    import yt_dlp  # type: ignore[import-untyped]
    from yt_dlp.extractor.youtube.pot._registry import (  # type: ignore[import-untyped]
        _pot_providers,
    )
    from yt_dlp.globals import plugin_dirs  # type: ignore[import-untyped]
    from yt_dlp.plugins import load_all_plugins  # type: ignore[import-untyped]

    args = list(sys.argv[1:] if argv is None else argv)
    proof = args.pop(0)
    if proof not in {"bgutil", "wpc"}:
        raise ValueError("unknown YouTube proof")
    parsed = yt_dlp.parse_options(args)
    plugin_dirs.value = parsed.options.plugin_dirs
    load_all_plugins()
    allowed = {"WPC"} if proof == "wpc" else {"BgUtilHTTP"}
    _pot_providers.value = {
        key: provider
        for key, provider in _pot_providers.value.items()
        if key in allowed
    }
    if not _pot_providers.value:
        raise RuntimeError("YouTube proof provider unavailable")
    with yt_dlp.YoutubeDL(parsed.ydl_opts) as downloader:
        if parsed.options.load_info_filename:
            return int(
                downloader.download_with_info_file(parsed.options.load_info_filename)
            )
        return int(downloader.download(parsed.urls))


if __name__ == "__main__":
    raise SystemExit(main())
