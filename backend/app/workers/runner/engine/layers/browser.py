"""L3 page oracle: no signed API construction and no external resolver."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from dataclasses import fields, replace
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app.services.provider_failures import FailureClass
from app.services.provider_types import ProviderIdentity
from app.workers.runner.browser_runtime import BrowserOperation, _finish
from app.workers.runner.engine import identity
from app.workers.runner.engine.browser import douyin, xiaohongshu, youtube
from app.workers.runner.engine.browser.intercept import (
    MAX_RESPONSE_BYTES,
    PageResponses,
    failure,
)
from app.workers.runner.engine.resolved import ResolvedMedia
from app.workers.runner.engine.run_context import ResolutionSource, RunContext
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.metadata import enrich_format_metadata
from app.workers.runner.utilities import normalize_for_settings
from playwright.async_api import Error

PARSERS = {"douyin": douyin, "xiaohongshu": xiaohongshu}


class _Handoff:
    """Cookie jar and native lease share exactly one terminal owner."""

    def __init__(
        self,
        operation: BrowserOperation,
        directory: Path,
        original_cookie: Path | None = None,
    ) -> None:
        self.operation = operation
        self.directory = directory
        self.original_cookie = original_cookie
        self.closed = False

    @property
    def user_agent(self) -> str:
        return self.operation.user_agent

    async def cookies(self) -> list[dict[str, object]]:
        return await self.operation.cookies()

    async def download(self, url: str, dest: Path) -> None:
        await self.operation.download(url, dest)

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            await _finish(self.operation.close())
        finally:
            await asyncio.to_thread(shutil.rmtree, self.directory)
            if self.original_cookie is not None:
                await _remove_identity(self.original_cookie)


async def _remove_identity(cookie: Path) -> None:
    # Identity client owns one private operation directory, never a shared profile.
    if (
        cookie.is_relative_to(identity.COOKIE_TMPFS_ROOT)
        and len(cookie.relative_to(identity.COOKIE_TMPFS_ROOT).parts) == 2
    ):
        await asyncio.to_thread(shutil.rmtree, cookie.parent, True)


def _expected_id(url: str, platform: str) -> str | None:
    parsed = urlsplit(url)
    segments = parsed.path.strip("/").split("/")
    if platform == "douyin":
        value = parse_qs(parsed.query).get("modal_id", [segments[-1]])[0]
        return value if value.isdigit() else None
    value = segments[-1]
    return (
        value
        if len(value) == 24 and all(c in "0123456789abcdef" for c in value)
        else None
    )


async def _cookie_jar(operation: BrowserOperation, directory: Path) -> Path:
    lines = ["# Netscape HTTP Cookie File"]
    for cookie in await operation.cookies():
        domain, name, value, path = (
            str(cookie.get(k, "")) for k in ("domain", "name", "value", "path")
        )
        if any(
            any(c in field for c in "\t\r\n\x00")
            for field in (domain, name, value, path)
        ):
            raise failure(FailureClass.INVALID_INPUT, "invalid_cookie", "none")
        if cookie.get("httpOnly"):
            domain = f"#HttpOnly_{domain}"
        lines.append(
            "\t".join(
                (
                    domain,
                    "TRUE" if str(cookie["domain"]).startswith(".") else "FALSE",
                    path,
                    "TRUE" if cookie.get("secure") else "FALSE",
                    str(max(0, int(float(str(cookie.get("expires", 0)))))),
                    name,
                    value,
                )
            )
        )
    jar = directory / "cookies.txt"
    payload = ("\n".join(lines) + "\n").encode()
    if len(payload) > 1024**2:
        raise failure(FailureClass.INVALID_INPUT, "cookie_limit", "none")
    jar.touch(mode=0o600)
    jar.write_bytes(payload)
    return jar


class BrowserLayer:
    async def resolve(self, source: ResolutionSource, ctx: RunContext) -> ResolvedMedia:
        profile = source.request.profile
        if profile.key == "youtube":
            return await youtube.resolve(source, ctx)
        parser = PARSERS.get(profile.key)
        runtime = source.pipeline.browser
        if parser is None or runtime is None:
            raise failure(
                FailureClass.RUNTIME_UNAVAILABLE, "browser_not_implemented", "none"
            )
        if profile.identity is ProviderIdentity.NONE and ctx.identity is not None:
            raise failure(FailureClass.INVALID_INPUT, "unexpected_identity", "none")
        if profile.identity is ProviderIdentity.REQUIRED and ctx.identity is None:
            fetched = await identity.fetch_identity(
                profile.key, source.workspace.path.name, ctx.deadline
            )
            ctx = ctx.with_material(identity=fetched)
        try:
            operation = await runtime.acquire(
                profile, ctx=ctx, task_id=source.workspace.path.name
            )
        except BaseException:
            if ctx.identity is not None:
                await _remove_identity(ctx.identity.cookie_file)
            raise
        collector = PageResponses(
            operation.page, parser.RULES.platform, parser.RULES.response_patterns
        )
        directory: Path | None = None
        try:
            await operation.navigate(parser.HOME)
            # A document may have committed before its visitor initialization JS.
            await operation.page.wait_for_timeout(2000)
            collector.start()
            await operation.navigate(source.request.source_url)
            expected = _expected_id(source.request.source_url, profile.key)
            expected = expected or _expected_id(operation.page.url, profile.key)
            if expected is None:
                raise failure(FailureClass.EXTRACTOR_BROKEN, "work_identity_missing")
            media: ResolvedMedia | None = None
            for _ in range(40):
                state = await operation.page.evaluate(
                    f"() => {{ const value = ({parser.STATE})(); "
                    "const s = JSON.stringify(value); "
                    f"return s && s.length <= {MAX_RESPONSE_BYTES} ? s : null; }}"
                )
                payloads = []
                if isinstance(state, str):
                    payload = json.loads(state)
                    if isinstance(payload, dict):
                        payloads.append(payload)
                while not collector.queue.empty():
                    payloads.append(collector.queue.get_nowait())
                for payload in payloads:
                    try:
                        media = parser.parse_response(payload, expected)
                        break
                    except RunnerFailure as error:
                        if (
                            error.failure.failure_class
                            is not FailureClass.EXTRACTOR_BROKEN
                        ):
                            raise
                if media is not None:
                    break
                error_code = parse_qs(urlsplit(operation.page.url).query).get(
                    "error_code", []
                )
                if "300031" in error_code:
                    raise failure(
                        FailureClass.CONTENT_UNAVAILABLE, "note_unavailable", "none"
                    )
                if "300012" in error_code:
                    raise failure(FailureClass.CHALLENGE, "request_verification")
                await operation.page.wait_for_timeout(1000)
            if media is None:
                raise failure(FailureClass.CHALLENGE, "page_media_missing")
            identity.COOKIE_TMPFS_ROOT.mkdir(mode=0o700, exist_ok=True)
            directory = Path(
                tempfile.mkdtemp(prefix="browser-", dir=identity.COOKIE_TMPFS_ROOT)
            )
            jar = await _cookie_jar(operation, directory)
            material = (
                identity.IdentityMaterial(jar, ctx.identity.digest)
                if ctx.identity
                else None
            )
            handoff = _Handoff(
                operation, directory, ctx.identity.cookie_file if ctx.identity else None
            )
            updated = replace(
                ctx,
                cookie_file=jar,
                identity=material,
                browser=handoff,
                user_agent=operation.user_agent,
                referer=operation.page.url,
            )
            commands = source.pipeline._commands.with_context(updated)
            payload = media.download_info
            # Reuse the media probe to establish actual codecs/fps, not guesses.
            usable = []
            handoff_kind = media.handoff
            for raw in payload["formats"][:8]:
                try:
                    probe = await commands.probe_remote(
                        raw["url"], source.workspace.path, referer=updated.referer
                    )
                    usable.append(enrich_format_metadata(raw, probe))
                except RunnerFailure:
                    # Only a successful native media response proves browser binding.
                    if raw["url"] not in collector.media_urls:
                        raise
                    handoff_kind = "browser"
                    usable = [raw]
                    break
            payload["formats"] = usable
            if handoff_kind == "http":
                # Stop page playback as soon as native transfer is unnecessary.
                await operation.page.close()
            normalized = normalize_for_settings(payload, source.pipeline._settings)
            return ResolvedMedia(
                **{f.name: getattr(normalized, f.name) for f in fields(normalized)},
                client=media.client,
                handoff=handoff_kind,
                run_context=updated,
            )
        except BaseException as error:
            await _finish(operation.abort())
            if directory is not None:
                await asyncio.to_thread(shutil.rmtree, directory)
            if ctx.identity is not None:
                await _remove_identity(ctx.identity.cookie_file)
            if isinstance(error, Error):
                raise failure(
                    FailureClass.CHALLENGE, "page_navigation_failed"
                ) from None
            raise
        finally:
            await collector.close()
