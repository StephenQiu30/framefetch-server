"""Builder for bounded yt-dlp commands from one resolved provider request."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.provider_types import ProviderAccessMode
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_errors import ProviderFailureContext
from app.workers.runner.provider_registry import ProviderRequest, provider_request
from app.workers.runner.settings import RunnerSettings


@dataclass(frozen=True, slots=True)
class BuiltYtDlpCommand:
    argv: tuple[str, ...]
    request: ProviderRequest
    egress_proxy: str
    authenticated: bool

    @property
    def failure_context(self) -> ProviderFailureContext:
        return ProviderFailureContext(
            provider_key=self.request.profile.key,
            source_url=self.request.source_url,
            authenticated=self.authenticated,
        )


class YtDlpCommandBuilder:
    def __init__(self, settings: RunnerSettings, plugin_root: Path) -> None:
        self._settings = settings
        self._plugin_root = plugin_root

    def inspect(
        self,
        source: str | ProviderRequest,
        *,
        cookie_jar: Path | None,
    ) -> BuiltYtDlpCommand:
        request = self._resolve(source)
        return self._build(
            request,
            (
                "--dump-single-json",
                "--skip-download",
                "--ignore-no-formats-error",
                "--playlist-end",
                str(self._settings.runner_max_gallery_assets + 1),
            ),
            cookie_jar=cookie_jar,
            include_playlist=True,
        )

    def download(
        self,
        source: str | ProviderRequest,
        provider_id: str,
        output: Path,
        *,
        max_bytes: int,
        cookie_jar: Path | None,
        info_json: Path | None = None,
        disable_cache: bool = False,
    ) -> BuiltYtDlpCommand:
        request = self._resolve(source)
        operation_args: tuple[str, ...] = ("--no-cache-dir",) if disable_cache else ()
        operation_args += (
            "--format",
            provider_id,
            "--max-filesize",
            str(max_bytes),
            "--output",
            str(output),
        )
        if info_json is not None:
            operation_args += ("--load-info-json", str(info_json))
        return self._build(
            request,
            operation_args,
            cookie_jar=cookie_jar,
            include_source=info_json is None,
        )

    def download_collection(
        self,
        source: str | ProviderRequest,
        output_dir: Path,
        *,
        max_bytes: int,
        max_entries: int,
        cookie_jar: Path | None,
    ) -> BuiltYtDlpCommand:
        if max_bytes <= 0 or max_entries <= 0:
            raise ValueError("collection download limits must be positive")
        request = self._resolve(source)
        operation_args = (
            "--yes-playlist",
            "--format",
            "bestvideo*+bestaudio/best",
            "--max-filesize",
            str(max_bytes),
            "--playlist-end",
            str(max_entries),
            "--restrict-filenames",
            "--output",
            str(output_dir / "video-%(playlist_index)04d.%(ext)s"),
        )
        return self._build(
            request,
            operation_args,
            cookie_jar=cookie_jar,
            include_playlist=True,
        )

    def _build(
        self,
        request: ProviderRequest,
        operation_args: tuple[str, ...],
        *,
        cookie_jar: Path | None,
        include_source: bool = True,
        include_playlist: bool = False,
    ) -> BuiltYtDlpCommand:
        profile = request.profile
        # The access context already admitted the jar from the session broker.
        if (
            cookie_jar is not None
            and self._settings.runner_access_mode is ProviderAccessMode.ANONYMOUS
        ):
            raise RunnerFailure("provider_session_not_allowed", status=422)
        egress_proxy = self._settings.egress_proxy_for(profile.key)
        command: tuple[str, ...] = (
            self._settings.runner_ytdlp_bin,
            "--ignore-config",
            "--plugin-dirs",
            str(self._plugin_root),
            "--no-progress",
            "--retries",
            "0"
            if "--skip-download" in operation_args
            else str(profile.yt_dlp_retry_count),
            "--fragment-retries",
            "0"
            if "--skip-download" in operation_args
            else str(profile.yt_dlp_retry_count),
            "--extractor-retries",
            "0",
            "--js-runtimes",
            self._settings.runner_ytdlp_js_runtime,
            "--proxy",
            egress_proxy,
        )
        if not include_playlist:
            command += ("--no-playlist",)
        if cookie_jar is not None:
            command += ("--cookies", str(cookie_jar))
        command += (*operation_args, *profile.command_args_for(self._settings))
        if include_source:
            command += ("--", request.request_url)
        return BuiltYtDlpCommand(
            argv=command,
            request=request,
            egress_proxy=egress_proxy,
            authenticated=cookie_jar is not None,
        )

    @staticmethod
    def _resolve(source: str | ProviderRequest) -> ProviderRequest:
        return provider_request(source) if isinstance(source, str) else source
