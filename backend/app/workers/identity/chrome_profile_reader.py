"""yt-dlp owns Chrome extraction; its UI-capable key lookup is never called."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from app.workers.runner.netscape_cookie import (
    has_safe_cookie_fields,
    is_allowed_domain,
    serialize_cookies,
)
from app.workers.runner.provider_registry import provider_profile_for_key


class _QuietLogger:
    def __init__(self) -> None:
        self.failed = False
        self.decryption_failed = False

    def debug(self, *args: object, **kwargs: object) -> None:
        pass

    info = debug

    def warning(self, message: str, *args: object, **kwargs: object) -> None:
        if "decrypt" in message.casefold():
            self.decryption_failed = True

    def error(self, *args: object, **kwargs: object) -> None:
        self.failed = True


def read_cookies(profile: Path, site: str, password: bytes) -> bytes:
    import yt_dlp.cookies as cookies  # type: ignore[import-untyped]

    if not profile.is_dir() or not (profile / "Cookies").is_file():
        raise FileNotFoundError("chrome_profile_missing")
    # yt-dlp's os.walk suppresses directory permission errors. Surface host
    # access denial rather than incorrectly claiming a missing Profile/logout.
    with os.scandir(profile) as entries:
        next(entries, None)
    original = cookies._get_mac_keyring_password
    cookies._get_mac_keyring_password = lambda *args: password
    logger = _QuietLogger()
    try:
        jar = cookies.extract_cookies_from_browser(
            "chrome", profile=str(profile), logger=logger
        )
    finally:
        cookies._get_mac_keyring_password = original
    if logger.failed:
        raise ValueError("source_read_failed")
    if logger.decryption_failed:
        raise ValueError("cookie_decryption_failed")
    target = provider_profile_for_key(site)
    selected = [
        item
        for item in jar
        if is_allowed_domain(item.domain, target.cookie_domain_allowlist)
        and item.value
        and (item.expires is None or item.expires > time.time())
        and has_safe_cookie_fields(item)
    ]
    if not selected:
        raise LookupError("site_not_logged_in")
    return serialize_cookies(selected)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--site", required=True)
    args = parser.parse_args()
    # A private stdin pipe carries the cached storage password. Never argv/env/disk.
    password = sys.stdin.buffer.read(16385)
    if not 0 < len(password) <= 16384:
        return 65
    try:
        payload = read_cookies(args.profile, args.site, password)
    except PermissionError:
        return 69
    except FileNotFoundError:
        return 66
    except LookupError:
        return 67
    except ValueError as error:
        return 68 if str(error) == "cookie_decryption_failed" else 65
    except Exception:
        return 65
    sys.stdout.buffer.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
