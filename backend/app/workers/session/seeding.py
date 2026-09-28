"""The one rule for accepting a login as a site session seed.

Shared by the browser (before it adopts a login profile) and the broker (before
it stores the seed), so the two can never disagree.
"""

from __future__ import annotations

from app.integrations.site_session_catalog import SiteTarget
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.netscape_cookie import (
    live_cookie_payload,
    parse_cookie_payload,
)


def seedable_payload(jar: bytes, target: SiteTarget, now: float) -> bytes | None:
    """Live site cookies with a persistent login the registry accepts, or None."""
    try:
        payload, names = live_cookie_payload(jar, target.cookie_domains, now=now)
        lines = parse_cookie_payload(payload, target.cookie_domains)
    except RunnerFailure:
        return None
    persistent = any(line.expires > 0 for line in lines)
    return payload if persistent and target.policy.accepts(names) else None
