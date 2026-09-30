"""One isolated, bounded Chrome read. stdout is a private, site-scoped pipe."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from app.integrations.site_session_catalog import known_session_sites, site_target
from app.workers.runner.netscape_cookie import (
    has_safe_cookie_fields,
    is_allowed_domain,
    serialize_cookies,
)
from app.workers.session.macos_keychain import (
    KeychainUnavailable,
    chrome_storage_password,
)


class _QuietLogger:
    def __init__(self) -> None:
        self.failed = False
        self.warned = False

    def debug(self, *args: object, **kwargs: object) -> None:
        pass

    info = debug

    def warning(self, *args: object, **kwargs: object) -> None:
        self.warned = True

    def error(self, *args: object, **kwargs: object) -> None:
        self.failed = True


def read_cookies(profile: Path, site: str) -> bytes:
    # yt-dlp owns extraction and decryption. Replace only its UI-capable key
    # lookup in this isolated child with an OS read that refuses interaction.
    import yt_dlp.cookies as cookies  # type: ignore[import-untyped]

    password = chrome_storage_password()
    cookies._get_mac_keyring_password = lambda *args: password
    logger = _QuietLogger()
    jar = cookies.extract_cookies_from_browser(
        "chrome", profile=str(profile), logger=logger
    )
    if logger.failed:
        raise ValueError("source_read_failed")
    target = site_target(site)
    selected = [
        item
        for item in jar
        if is_allowed_domain(item.domain, target.cookie_domains)
        and item.value
        and (item.expires is None or item.expires > time.time())
        and has_safe_cookie_fields(item)
    ]
    if not target.policy.accepts(frozenset(item.name for item in selected)):
        if logger.warned:
            raise ValueError("source_read_failed")
        raise LookupError("credential_required")
    return serialize_cookies(selected)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--site", choices=known_session_sites(), required=True)
    args = parser.parse_args()
    try:
        payload = read_cookies(args.profile, args.site)
    except KeychainUnavailable as exc:
        return 77 if exc.access_denied else 65
    except FileNotFoundError:
        return 66
    except LookupError:
        return 67
    except Exception:
        return 65
    sys.stdout.buffer.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
