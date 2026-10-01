from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.workers.runner.settings import RunnerSettings

YTDLP_ENGINE_VERSION = "2026.8.19"
YTDLP_ENGINE_COMMIT = "51bab8a0116f4d8004c315706d809782607d5847"
YOUTUBE_POT_PROVIDER_VERSION = "2.0.0"
YOUTUBE_POT_PROVIDER_ATTESTATION = f"bgutil-http-{YOUTUBE_POT_PROVIDER_VERSION}"


def engine_revision(settings: RunnerSettings | None = None) -> str:
    """Digest the installed engines and shipped plugin/browser implementation."""
    import hashlib
    import json
    from importlib.metadata import PackageNotFoundError, version
    from pathlib import Path

    from app.workers.runner.browser_runtime import CHROMIUM_VERSION

    facts = {}
    for package in (
        "yt-dlp",
        "bgutil-ytdlp-pot-provider",
        "yt-dlp-ejs",
        "yt-dlp-getpot-wpc",
        "playwright",
    ):
        try:
            facts[package] = version(package)
        except PackageNotFoundError:
            facts[package] = "absent"
    facts["yt-dlp-commit"] = (
        settings.runner_ytdlp_commit if settings else YTDLP_ENGINE_COMMIT
    )
    facts["javascript-runtime"] = (
        settings.runner_ytdlp_js_runtime if settings else "node"
    )
    facts["bgutil-service"] = (
        settings.runner_youtube_pot_provider_version
        if settings
        else YOUTUBE_POT_PROVIDER_ATTESTATION
    )
    facts["chromium"] = CHROMIUM_VERSION
    digest = hashlib.sha256(json.dumps(facts, sort_keys=True).encode())
    root = Path(__file__).resolve().parent
    # Local layer/proof code changes also invalidate previously confirmed plans.
    paths = [*(root / "plugins").rglob("*.py"), *(root / "engine").rglob("*.py")]
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()
