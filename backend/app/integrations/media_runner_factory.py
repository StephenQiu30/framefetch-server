"""Validated construction of deployment session Runner clients."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.core.config import Settings
from app.integrations.media_inspection_pipeline import SessionPolicyReader
from app.integrations.media_runner import MediaRunnerHttpClient, MediaRunnerRouter
from app.services.provider_route_admission import ProviderRouteAdmission
from app.services.provider_types import ProviderAccessContextRef, ProviderAccessMode
from app.services.site_sessions import known_session_provider_keys


def session_media_runner(
    settings: Settings, admission: ProviderRouteAdmission | None = None
) -> MediaRunnerHttpClient | None:
    if settings.session_runner_base_url is None:
        return None
    return _media_runner(
        settings,
        settings.session_runner_base_url,
        admission,
        ProviderAccessMode.OPERATOR_MANAGED,
    )


def media_runner_router(
    settings: Settings,
    admission: ProviderRouteAdmission | None = None,
    *,
    session_routes: SessionPolicyReader,
) -> MediaRunnerRouter:
    session = session_media_runner(settings, admission)
    if session is None:
        raise ValueError("SESSION_RUNNER_BASE_URL is required")
    return MediaRunnerRouter(session, session_routes=session_routes)


def session_provider_keys(settings: Settings) -> frozenset[str]:
    """Known providers that can use a site session in this deployment."""
    if settings.session_runner_base_url is None:
        return frozenset()
    return known_session_provider_keys()


def _media_runner(
    settings: Settings,
    base_url: str,
    admission: ProviderRouteAdmission | None,
    access_mode: ProviderAccessMode,
    reject_guest: Callable[[ProviderAccessContextRef], Awaitable[None]] | None = None,
) -> MediaRunnerHttpClient:
    return MediaRunnerHttpClient(
        base_url=base_url,
        secret=settings.runner_hmac_secret.get_secret_value().encode(),
        workspace_root=settings.runner_workspace_root,
        inspect_timeout_seconds=settings.inspect_timeout_seconds,
        download_timeout_seconds=settings.download_timeout_seconds,
        admission=admission,
        expected_access_mode=access_mode,
        reject_guest=reject_guest,
    )
