"""Deterministic source adapters for provider-scoped browser sessions."""

from __future__ import annotations

from collections.abc import Callable
from http.cookiejar import CookieJar

from app.workers.runner.provider_session_policy import (
    ProviderBrowserSessionPolicy,
    ProviderSessionSource,
)
from app.workers.runner.yuanbao_session import YuanbaoSession
from app.workers.session.chrome_reader import extract_chrome_cookies

type ProviderSessionLoader = Callable[[ProviderBrowserSessionPolicy, str], CookieJar]


def load_provider_session(
    policy: ProviderBrowserSessionPolicy,
    profile: str,
) -> CookieJar:
    if policy.source is ProviderSessionSource.CHROME_PROFILE:
        return extract_chrome_cookies(policy.domains, profile)
    if policy.source is ProviderSessionSource.MANAGED_YUANBAO:
        return YuanbaoSession().load()
    raise ValueError("unsupported provider session source")
