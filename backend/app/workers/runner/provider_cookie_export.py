"""Export one provider-scoped Chrome Cookie jar as an in-memory lease."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from http.cookiejar import Cookie
from pathlib import Path
from typing import Final

from app.services.provider_types import ProviderKey, ProviderSessionVersion
from app.workers.runner.netscape_cookie import (
    has_safe_cookie_fields,
    is_allowed_domain,
    serialize_cookies,
)
from app.workers.runner.provider_cookie_lease import (
    ProviderCookieLease,
    ProviderCookieLeaseStatus,
)
from app.workers.runner.provider_session_policy import (
    ProviderSessionSource,
    browser_session_policy,
)
from app.workers.runner.provider_session_source import (
    ProviderSessionLoader,
    load_provider_session,
)
from app.workers.session.chrome_reader import extract_chrome_cookies

OK: Final = ProviderCookieLeaseStatus.OK
CREDENTIAL_REQUIRED: Final = ProviderCookieLeaseStatus.CREDENTIAL_REQUIRED
SOURCE_MISSING: Final = ProviderCookieLeaseStatus.SOURCE_MISSING
PERMISSION_DENIED: Final = ProviderCookieLeaseStatus.PERMISSION_DENIED
SESSION_UNAVAILABLE: Final = ProviderCookieLeaseStatus.SESSION_UNAVAILABLE

_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def export_provider_cookie_lease(
    *,
    provider: ProviderKey,
    profile: str,
    version: ProviderSessionVersion,
    chrome_root: Path | None = None,
    load: ProviderSessionLoader = load_provider_session,
    clock: Callable[[], float] = time.time,
) -> ProviderCookieLease:
    """Return one allowlisted Cookie payload without retaining it on disk."""
    policy = browser_session_policy(provider)
    if version is not policy.version or _VERSION.fullmatch(version.value) is None:
        return ProviderCookieLease(SESSION_UNAVAILABLE)
    try:
        if (
            chrome_root is not None
            and policy.source is ProviderSessionSource.CHROME_PROFILE
        ):
            jar = extract_chrome_cookies(
                policy.domains,
                profile,
                chrome_root=chrome_root,
            )
        else:
            jar = load(policy, profile)
        now = int(clock())
        cookies = tuple(
            cookie for cookie in jar if eligible_cookie(cookie, policy.domains, now)
        )
        cookie_names = frozenset(cookie.name for cookie in cookies)
        if not cookies or not policy.accepts(cookie_names):
            return ProviderCookieLease(CREDENTIAL_REQUIRED)
        payload = cookie_payload(cookies)
    except FileNotFoundError:
        return ProviderCookieLease(SOURCE_MISSING)
    except PermissionError:
        return ProviderCookieLease(PERMISSION_DENIED)
    except Exception:
        return ProviderCookieLease(SESSION_UNAVAILABLE)
    return ProviderCookieLease(OK, payload)


def eligible_cookie(cookie: Cookie, allowed_domains: Iterable[str], now: int) -> bool:
    return (
        is_allowed_domain(cookie.domain, allowed_domains)
        and not cookie.is_expired(now)
        and cookie.path.startswith("/")
        and has_safe_cookie_fields(cookie)
    )


def cookie_payload(cookies: tuple[Cookie, ...]) -> bytes:
    return serialize_cookies(cookies)
