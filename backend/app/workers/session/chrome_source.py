"""Read an approved Chrome Profile per operation, without browser interaction."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.integrations.site_session_catalog import known_session_sites, site_target
from app.workers.runner.netscape_cookie import MAX_COOKIE_BYTES, parse_cookie_payload
from app.workers.runner.process import ProcessSupervisor, ProcessTimeoutError
from app.workers.runner.provider_session_files import validated_cookie_payload


class SourceUnavailable(Exception):
    def __init__(self, code: str = "provider_session_not_ready") -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    site: str
    generation: int
    cookies: bytes = field(repr=False)
    headers: bytes | None = field(default=None, repr=False)


class ChromeSource:
    def __init__(
        self,
        *,
        secret: bytes,
        profile: Path,
        read_timeout_seconds: float = 15,
    ) -> None:
        if not profile.is_absolute() or not 1 <= read_timeout_seconds <= 60:
            raise ValueError("invalid Chrome source configuration")
        self._secret = secret
        self._profile = profile.resolve()
        self._timeout = read_timeout_seconds
        self._lock = asyncio.Lock()
        self._reads: set[asyncio.Task[bytes]] = set()
        self._started = False
        self._process = ProcessSupervisor(stdout_limit_bytes=MAX_COOKIE_BYTES)

    async def start(self) -> None:
        self._started = True

    async def close(self) -> None:
        self._started = False
        tasks = tuple(self._reads)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def read(self, site: str, *, include_headers: bool = False) -> SourceSnapshot:
        if site not in known_session_sites():
            raise SourceUnavailable("provider_session_not_allowed")
        if not self._started:
            raise SourceUnavailable()
        target = site_target(site)
        if include_headers and target.policy.header_plugin is not None:
            raise SourceUnavailable()
        try:
            async with asyncio.timeout(self._timeout):
                async with self._lock:
                    if not self._started:
                        raise SourceUnavailable()
                    task = asyncio.create_task(self._read(site))
                    self._reads.add(task)
                    try:
                        payload = await task
                    finally:
                        self._reads.discard(task)
        except TimeoutError:
            raise SourceUnavailable("source_read_timeout") from None
        except OSError:
            raise SourceUnavailable() from None
        try:
            payload = validated_cookie_payload(payload, target.cookie_domains)
            entries = parse_cookie_payload(payload, target.cookie_domains)
            if not target.policy.accepts(frozenset(entry.name for entry in entries)):
                raise SourceUnavailable("credential_required")
            identity = sorted(
                entry.line.decode()
                for entry in entries
                if not target.policy.required_cookie_names
                or entry.name in target.policy.required_cookie_names
            )
            digest = hmac.digest(
                self._secret,
                json.dumps(
                    [str(self._profile), site, identity], separators=(",", ":")
                ).encode(),
                hashlib.sha256,
            )
        except SourceUnavailable:
            raise
        except Exception:
            raise SourceUnavailable("source_read_failed") from None
        return SourceSnapshot(site, int.from_bytes(digest[:16], "big") + 1, payload)

    async def _read(self, site: str) -> bytes:
        if not self._profile.is_dir() or not any(
            (self._profile / item).is_file() for item in ("Cookies", "Network/Cookies")
        ):
            raise SourceUnavailable("chrome_profile_unavailable")
        with tempfile.TemporaryDirectory(prefix="framefetch-chrome-read-") as raw:
            try:
                result = await self._process.run(
                    [
                        sys.executable,
                        "-m",
                        "app.workers.session.chrome_profile_reader",
                        "--profile",
                        str(self._profile),
                        "--site",
                        site,
                    ],
                    cwd=Path(__file__).resolve().parents[3],
                    timeout_seconds=self._timeout,
                    env={"PATH": os.defpath, "TMPDIR": raw},
                )
            except ProcessTimeoutError:
                raise SourceUnavailable("source_read_timeout") from None
        if result.returncode != 0:
            raise SourceUnavailable(
                {
                    77: "credential_access_denied",
                    66: "chrome_profile_unavailable",
                    67: "credential_required",
                }.get(result.returncode, "source_read_failed")
            )
        if result.stdout_truncated:
            raise SourceUnavailable("source_read_failed")
        return result.stdout
