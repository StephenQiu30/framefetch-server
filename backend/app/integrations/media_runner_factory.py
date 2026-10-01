"""Construct the one deployment Media Runner from typed settings."""

from app.core.config import Settings
from app.integrations.media_runner import MediaRunnerHttpClient, MediaRunnerRouter


def session_media_runner(settings: Settings) -> MediaRunnerHttpClient | None:
    if settings.session_runner_base_url is None:
        return None
    return MediaRunnerHttpClient(
        base_url=settings.session_runner_base_url,
        secret=settings.runner_hmac_secret.get_secret_value().encode(),
        workspace_root=settings.runner_workspace_root,
        inspect_timeout_seconds=settings.inspect_timeout_seconds,
        download_timeout_seconds=settings.download_timeout_seconds,
    )


def media_runner_router(settings: Settings) -> MediaRunnerRouter:
    runner = session_media_runner(settings)
    if runner is None:
        raise ValueError("SESSION_RUNNER_BASE_URL is required")
    return MediaRunnerRouter(runner)
