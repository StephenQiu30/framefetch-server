from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import copy
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol

import httpx
from app.services.downloads.rules.enums import Container, MediaKind
from app.services.provider_failures import (
    FailureClass,
    FailureEvidenceKind,
    FailurePhase,
    failure_definition,
    parse_retry_after,
)
from app.services.provider_types import ProviderKey
from app.workers.runner.command_support import child_environment, json_object
from app.workers.runner.engine.run_context import RunContext
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.metadata import (
    collection_fallback_assets,
    normalize_media_payload,
)
from app.workers.runner.process import ProcessResult, ProcessTimeoutError
from app.workers.runner.provider_errors import (
    ProviderFailureContext,
    classify_provider_failure,
)
from app.workers.runner.provider_registry import ProviderRequest, provider_request
from app.workers.runner.settings import RunnerSettings
from app.workers.runner.utilities import safe_media_url
from app.workers.runner.workspace_monitor import (
    WorkspaceLimitExceeded,
    run_with_workspace_limit,
)
from app.workers.runner.yt_dlp_commands import YtDlpCommandBuilder

_YTDLP_PLUGIN_ROOT = Path(__file__).resolve().parent
_REMOTE_PROBE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)
_POT_PROBE_TIMEOUT_SECONDS = 2.0
_LOGGER = logging.getLogger(__name__)
PotProviderProbe = Callable[[str], Awaitable[bool]]


class ProcessRunner(Protocol):
    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult: ...


class MediaCommands:
    def __init__(
        self,
        settings: RunnerSettings,
        supervisor: ProcessRunner,
        *,
        pot_provider_probe: PotProviderProbe | None = None,
    ) -> None:
        self._settings = settings
        self._supervisor = supervisor
        self._pot_provider_probe = pot_provider_probe or _pot_provider_ready
        self._ctx: RunContext | None = None
        self._client: str | None = None

    def with_context(self, ctx: RunContext) -> MediaCommands:
        result = copy(self)
        result._ctx = ctx
        return result

    def with_client(self, client: str) -> MediaCommands:
        result = copy(self)
        result._client = client
        return result

    @property
    def _run_context(self) -> RunContext:
        if self._ctx is None:
            raise RunnerFailure("invalid_input", status=422)
        return self._ctx

    @property
    def _ytdlp(self) -> YtDlpCommandBuilder:
        return YtDlpCommandBuilder(
            self._settings, _YTDLP_PLUGIN_ROOT, self._run_context, client=self._client
        )

    async def inspect(
        self,
        source: str | ProviderRequest,
        cwd: Path,
        *,
        cookie_jar: Path | None = None,
    ) -> dict[str, Any]:
        command = self._ytdlp.inspect(source, cookie_jar=cookie_jar)
        result = await self._run(
            command.argv,
            cwd,
            self._settings.runner_inspect_timeout_seconds,
            timeout_code="inspection_timeout",
            failure_code="inspection_failed",
            phase=FailurePhase.FETCH_METADATA,
            egress_proxy=command.egress_proxy,
            failure_context=command.failure_context,
        )
        # Explicit content restrictions precede asset parsing/validation. Only
        # the DRM warning rule may be superseded by a clear candidate below.
        restriction = classify_provider_failure(
            command.failure_context, result.stderr, has_clear_media=True
        )
        if restriction is None or restriction[0] not in {
            "content_unavailable",
            "content_protected",
        }:
            payload = normalize_media_payload(
                json_object(result.stdout, "invalid_inspection_response"),
                max_assets=self._settings.runner_max_gallery_assets,
            )
            has_media = _inspection_payload_has_media(payload)
            restriction = classify_provider_failure(
                command.failure_context, result.stderr, has_clear_media=has_media
            )
            if restriction is None or has_media:
                return payload
        raise RunnerFailure(
            restriction[0],
            status=restriction[1],
            phase=FailurePhase.FETCH_METADATA,
            evidence_kind=FailureEvidenceKind.UPSTREAM_RESPONSE,
        )

    async def probe_remote(
        self,
        url: str,
        cwd: Path,
        *,
        referer: str | None = None,
        failure_context: ProviderFailureContext | None = None,
    ) -> dict[str, Any]:
        failure_context = failure_context or self._failure_context(referer or url)
        egress_proxy = self._run_context.egress.proxy_url
        command = (
            self._settings.runner_ffprobe_bin,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            "-protocol_whitelist",
            "http,https,tcp,tls,crypto,httpproxy",
            "-user_agent",
            self._run_context.user_agent or _REMOTE_PROBE_USER_AGENT,
            "-referer",
            referer or url,
            url,
        )
        result = await self._run(
            command,
            cwd,
            self._settings.runner_inspect_timeout_seconds,
            timeout_code="inspection_timeout",
            failure_code="media_probe_failed",
            phase=FailurePhase.PROBE_MEDIA,
            egress_proxy=egress_proxy,
            failure_context=failure_context,
        )
        return json_object(result.stdout, "media_probe_failed")

    async def probe_remote_prefix(
        self,
        url: str,
        cwd: Path,
        *,
        referer: str,
        failure_context: ProviderFailureContext | None = None,
    ) -> dict[str, Any]:
        # A throttled CDN must not force inspection to fetch an entire segment.
        # Only a small clear prefix is needed to identify codecs.
        failure_context = failure_context or self._failure_context(referer)
        limit = 8 * 1024
        data = bytearray()
        try:
            async with httpx.AsyncClient(
                proxy=self._run_context.egress.proxy_url,
                timeout=10,
                follow_redirects=True,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "GET",
                    url,
                    headers={"Range": f"bytes=0-{limit - 1}", "Referer": referer},
                ) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk[: limit - len(data)])
                        if len(data) == limit:
                            break
        except httpx.HTTPStatusError as exc:
            raise self._provider_failure(
                failure_context,
                f"http error {exc.response.status_code}".encode(),
                fallback_code="media_probe_failed",
                fallback_status=502,
                phase=FailurePhase.PROBE_MEDIA,
                retry_after=parse_retry_after(
                    exc.response.headers.get("Retry-After"), datetime.now(UTC)
                ),
            ) from exc
        except httpx.HTTPError as exc:
            raise RunnerFailure(
                "network_transient",
                status=503,
                phase=FailurePhase.PROBE_MEDIA,
                evidence_kind=FailureEvidenceKind.TRANSPORT,
            ) from exc
        if not data:
            raise RunnerFailure("media_probe_failed", status=502)
        with TemporaryDirectory(prefix="segment-probe-", dir=cwd) as directory:
            sample = Path(directory) / "prefix.input"
            sample.write_bytes(data)
            return await self.probe(
                sample,
                Path(directory),
                failure_context=failure_context,
            )

    async def download_stream(
        self,
        source: str | ProviderRequest,
        provider_id: str,
        output: Path,
        cwd: Path,
        *,
        cookie_jar: Path | None = None,
        info_json: Path | None = None,
    ) -> None:
        command = self._ytdlp.download(
            source,
            provider_id,
            output,
            max_bytes=self._settings.runner_max_output_bytes,
            cookie_jar=cookie_jar,
            info_json=info_json,
        )
        await self._run(
            command.argv,
            cwd,
            self._settings.runner_download_timeout_seconds,
            timeout_code="download_timeout",
            failure_code="download_failed",
            phase=FailurePhase.TRANSFER,
            monitor_workspace=True,
            egress_proxy=command.egress_proxy,
            failure_context=command.failure_context,
        )
        if not output.is_file() or output.is_symlink():
            raise RunnerFailure("download_failed", status=502)

    async def download_collection(
        self,
        source: str | ProviderRequest,
        output_dir: Path,
        cwd: Path,
        *,
        max_bytes: int,
        max_entries: int,
        cookie_jar: Path | None = None,
    ) -> None:
        output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        command = self._ytdlp.download_collection(
            source,
            output_dir,
            max_bytes=max_bytes,
            max_entries=max_entries,
            cookie_jar=cookie_jar,
        )
        await self._run(
            command.argv,
            cwd,
            self._settings.runner_download_timeout_seconds,
            timeout_code="download_timeout",
            failure_code="download_failed",
            phase=FailurePhase.TRANSFER,
            monitor_workspace=True,
            egress_proxy=command.egress_proxy,
            failure_context=command.failure_context,
        )

    async def download_public_asset(
        self,
        url: str,
        output: Path,
        cwd: Path,
        *,
        referer: str,
        max_bytes: int,
        failure_context: ProviderFailureContext | None = None,
    ) -> str:
        """Fetch one already-authorized public image through the provider egress."""
        del cwd
        failure_context = failure_context or self._failure_context(referer)
        safe_url = safe_media_url(url)
        try:
            selected_proxy = self._run_context.egress.proxy_url
            async with httpx.AsyncClient(
                proxy=selected_proxy,
                trust_env=False,
                follow_redirects=True,
                timeout=self._settings.runner_download_timeout_seconds,
            ) as client:
                async with client.stream(
                    "GET",
                    safe_url,
                    headers={
                        "Referer": referer,
                        "User-Agent": self._run_context.user_agent
                        or _REMOTE_PROBE_USER_AGENT,
                    },
                ) as response:
                    safe_media_url(str(response.url))
                    if response.status_code != 200:
                        raise self._provider_failure(
                            failure_context,
                            f"http error {response.status_code}".encode(),
                            fallback_code="download_failed",
                            fallback_status=502,
                            phase=FailurePhase.TRANSFER,
                            retry_after=parse_retry_after(
                                response.headers.get("Retry-After"), datetime.now(UTC)
                            ),
                        )
                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            if int(content_length) > max_bytes:
                                raise RunnerFailure(
                                    "workspace_limit_exceeded", status=413
                                )
                        except ValueError:
                            pass
                    total = 0
                    with output.open("wb") as handle:
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > max_bytes:
                                raise RunnerFailure(
                                    "workspace_limit_exceeded", status=413
                                )
                            handle.write(chunk)
                    return str(response.headers.get("content-type", ""))
        except httpx.HTTPError as exc:
            raise RunnerFailure(
                "network_transient",
                status=503,
                phase=FailurePhase.TRANSFER,
                evidence_kind=FailureEvidenceKind.TRANSPORT,
            ) from exc

    async def download_probe_sample(
        self,
        source: str | ProviderRequest,
        provider_id: str,
        output: Path,
        cwd: Path,
        *,
        cookie_jar: Path | None = None,
    ) -> None:
        command = self._ytdlp.download(
            source,
            provider_id,
            output,
            max_bytes=self._settings.runner_max_probe_sample_bytes,
            cookie_jar=cookie_jar,
            disable_cache=True,
        )
        await self._run(
            command.argv,
            cwd,
            self._settings.runner_inspect_timeout_seconds,
            timeout_code="inspection_timeout",
            failure_code="inspection_failed",
            phase=FailurePhase.PROBE_MEDIA,
            monitor_workspace=True,
            workspace_limit_bytes=self._settings.runner_max_probe_sample_bytes,
            egress_proxy=command.egress_proxy,
            failure_context=command.failure_context,
        )
        if (
            not output.is_file()
            or output.is_symlink()
            or output.stat().st_size > self._settings.runner_max_probe_sample_bytes
        ):
            raise RunnerFailure("inspection_failed", status=502)

    async def remux(
        self,
        inputs: tuple[Path, ...],
        output: Path,
        container: Container,
        cwd: Path,
        *,
        include_audio: bool = True,
        failure_context: ProviderFailureContext | None = None,
    ) -> None:
        command: list[str] = [
            self._settings.runner_ffmpeg_bin,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
        ]
        for source in inputs:
            command.extend(
                ("-protocol_whitelist", "file,crypto,data", "-i", str(source))
            )
        command.extend(("-map", "0:v:0"))
        if include_audio:
            command.extend(("-map", "0:a:0" if len(inputs) == 1 else "1:a:0"))
        command.extend(("-c", "copy", "-map_metadata", "-1"))
        if container is Container.MP4:
            command.extend(("-movflags", "+faststart"))
        command.extend(("-f", container.value, str(output)))
        await self._run(
            command,
            cwd,
            self._settings.runner_download_timeout_seconds,
            timeout_code="download_timeout",
            failure_code="remux_failed",
            phase=FailurePhase.VALIDATE,
            monitor_workspace=True,
            failure_context=failure_context,
        )

    async def probe(
        self,
        artifact: Path,
        cwd: Path,
        *,
        failure_context: ProviderFailureContext | None = None,
        phase: FailurePhase = FailurePhase.PROBE_MEDIA,
    ) -> dict[str, Any]:
        command = (
            self._settings.runner_ffprobe_bin,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            "-protocol_whitelist",
            "file,crypto,data",
            str(artifact),
        )
        result = await self._run(
            command,
            cwd,
            self._settings.runner_inspect_timeout_seconds,
            timeout_code="inspection_timeout",
            failure_code="media_probe_failed",
            phase=phase,
            failure_context=failure_context,
        )
        try:
            return json_object(result.stdout, "media_probe_failed")
        except RunnerFailure as error:
            error.during(phase)
            raise

    async def _run(
        self,
        command: Sequence[str],
        cwd: Path,
        timeout: float,
        *,
        timeout_code: str,
        failure_code: str,
        phase: FailurePhase,
        monitor_workspace: bool = False,
        workspace_limit_bytes: int | None = None,
        egress_proxy: str | None = None,
        failure_context: ProviderFailureContext | None = None,
    ) -> ProcessResult:
        selected_proxy = (
            egress_proxy
            if egress_proxy is not None
            else (self._ctx.egress.proxy_url if self._ctx is not None else "")
        )
        needs_pot_provider = command[0] == self._settings.runner_ytdlp_bin
        if needs_pot_provider:
            await self._ensure_youtube_pot_provider(failure_context)
        try:
            operation = self._supervisor.run(
                command,
                cwd=cwd,
                timeout_seconds=timeout,
                env=child_environment(cwd, selected_proxy),
            )
            if monitor_workspace:
                result = await run_with_workspace_limit(
                    operation,
                    root=cwd,
                    max_bytes=(
                        workspace_limit_bytes
                        if workspace_limit_bytes is not None
                        else self._settings.runner_max_workspace_bytes
                    ),
                    poll_interval_seconds=(
                        self._settings.runner_workspace_poll_interval_seconds
                    ),
                )
            else:
                result = await operation
        except ProcessTimeoutError as exc:
            raise RunnerFailure(
                timeout_code,
                status=504,
                phase=phase,
                evidence_kind=FailureEvidenceKind.RUNTIME,
            ) from exc
        except WorkspaceLimitExceeded as exc:
            raise RunnerFailure(
                "workspace_limit_exceeded",
                status=413,
                phase=phase,
                evidence_kind=FailureEvidenceKind.RUNTIME,
            ) from exc
        except OSError as exc:
            raise RunnerFailure(
                "runner_dependency_unavailable",
                status=503,
                phase=phase,
                evidence_kind=FailureEvidenceKind.RUNTIME,
            ) from exc
        if result.returncode != 0:
            # Close the small race where the sidecar dies after the preflight
            # but before yt-dlp asks it for a token.
            provider_failure = (
                classify_provider_failure(failure_context, result.stderr)
                if failure_context is not None
                else None
            )
            if needs_pot_provider and (
                provider_failure is None
                or failure_definition(provider_failure[0])[0]
                not in {
                    FailureClass.CONTENT_UNAVAILABLE,
                    FailureClass.CONTENT_PROTECTED,
                }
            ):
                await self._ensure_youtube_pot_provider(failure_context)
            if provider_failure is not None:
                code, status = provider_failure
                _log_command_failure(
                    operation=failure_code,
                    provider=(
                        failure_context.provider_key
                        if failure_context is not None
                        else None
                    ),
                    code=code,
                    returncode=result.returncode,
                    stderr_truncated=result.stderr_truncated,
                )
                raise RunnerFailure(
                    code,
                    status=status,
                    phase=phase,
                    evidence_kind=FailureEvidenceKind.UPSTREAM_RESPONSE,
                    retry_after=_stderr_retry_after(result.stderr),
                    evidence={
                        "kind": "upstream_response",
                        "returncode": result.returncode,
                        "stderr_truncated": result.stderr_truncated,
                        **({"http_status": status} if status == 429 else {}),
                    },
                )
            _log_command_failure(
                operation=failure_code,
                provider=(
                    failure_context.provider_key
                    if failure_context is not None
                    else None
                ),
                code=failure_code,
                returncode=result.returncode,
                stderr_truncated=result.stderr_truncated,
            )
            raise RunnerFailure(
                failure_code,
                status=502,
                phase=phase,
                evidence_kind=FailureEvidenceKind.UPSTREAM_RESPONSE,
            )
        return result

    async def _ensure_youtube_pot_provider(
        self,
        context: ProviderFailureContext | None,
    ) -> None:
        base_url = self._settings.runner_youtube_pot_base_url
        if (
            context is None
            or context.provider_key != ProviderKey.YOUTUBE
            or base_url is None
        ):
            return
        try:
            ready = await self._pot_provider_probe(base_url)
        except Exception:
            ready = False
        if not ready:
            raise RunnerFailure("runtime_unavailable", status=503)

    @staticmethod
    def _failure_context(url: str) -> ProviderFailureContext:
        request = provider_request(url)
        return ProviderFailureContext(
            provider_key=request.profile.key,
            source_url=request.source_url,
            authenticated=False,
        )

    @staticmethod
    def _provider_failure(
        context: ProviderFailureContext,
        stderr: bytes,
        *,
        fallback_code: str,
        fallback_status: int,
        phase: FailurePhase,
        retry_after: datetime | None = None,
    ) -> RunnerFailure:
        provider_failure = classify_provider_failure(context, stderr)
        if provider_failure is not None:
            code, status = provider_failure
            return RunnerFailure(
                code,
                status=status,
                phase=phase,
                evidence_kind=FailureEvidenceKind.UPSTREAM_RESPONSE,
                retry_after=retry_after,
                evidence={
                    "kind": "upstream_response",
                    **({"http_status": status} if status == 429 else {}),
                },
            )
        return RunnerFailure(
            fallback_code,
            status=fallback_status,
            phase=phase,
            evidence_kind=FailureEvidenceKind.UPSTREAM_RESPONSE,
        )


def _inspection_payload_has_media(payload: Mapping[str, Any]) -> bool:
    # Presence only: gallery normalization still validates every asset and URL.
    assets = payload.get("assets")
    if (
        payload.get("media_kind") == MediaKind.IMAGE_GALLERY.value
        and isinstance(assets, list)
        and any(
            isinstance(item, dict)
            and isinstance(item.get("url"), str)
            and bool(item["url"].strip())
            for item in assets
        )
    ):
        return True
    if (
        payload.get("has_drm") is not True
        and isinstance(payload.get("url"), str)
        and bool(payload["url"].strip())
    ):
        return True
    formats = payload.get("formats")
    if isinstance(formats, list) and any(
        isinstance(item, dict)
        and item.get("has_drm") is not True
        and isinstance(item.get("url"), str)
        and bool(item["url"].strip())
        for item in formats
    ):
        return True
    if collection_fallback_assets(dict(payload)):
        return True
    entries = payload.get("entries")
    return isinstance(entries, list) and any(
        isinstance(entry, dict) and _inspection_payload_has_media(entry)
        for entry in entries
    )


async def _pot_provider_ready(base_url: str) -> bool:
    try:
        async with asyncio.timeout(_POT_PROBE_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(
                timeout=_POT_PROBE_TIMEOUT_SECONDS,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                response = await client.get(f"{base_url}/ping")
    except (httpx.HTTPError, TimeoutError):
        return False
    return response.status_code == 200


def _log_command_failure(
    *,
    operation: str,
    provider: str | None,
    code: str,
    returncode: int,
    stderr_truncated: bool,
) -> None:
    _LOGGER.warning(
        "runner command failed operation=%s provider=%s code=%s "
        "returncode=%s stderr_truncated=%s",
        operation,
        provider or "internal",
        code,
        returncode,
        stderr_truncated,
    )


def _stderr_retry_after(stderr: bytes) -> datetime | None:
    # Only a bounded header value crosses the boundary; stderr itself is discarded.
    match = re.search(
        rb"(?im)^\s*(?:WARNING:\s*)?retry-after:\s*([^\r\n]{1,128})\s*$", stderr
    )
    if match is None:
        return None
    try:
        value = match[1].strip().decode("ascii")
    except UnicodeDecodeError:
        return None
    return parse_retry_after(value, datetime.now(UTC))
