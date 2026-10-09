"""Template pipeline for inspecting and enriching one provider request."""

from __future__ import annotations

import asyncio
import math
from copy import copy
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.provider_failures import FailurePhase
from app.services.provider_types import ExecutionContext
from app.workers.runner.browser_runtime import BrowserRuntime
from app.workers.runner.commands import MediaCommands
from app.workers.runner.engine.run_context import RunContext
from app.workers.runner.entitlements import enforce_media_rights
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.metadata import (
    MediaInspection,
    build_download_options,
    enrich_direct_metadata,
    enrich_format_metadata,
    normalize_media_payload,
    normalize_selected_format_metadata,
)
from app.workers.runner.provider_errors import ProviderFailureContext
from app.workers.runner.provider_registry import (
    ProviderRequest,
    current_provider_registry,
)
from app.workers.runner.settings import RunnerSettings
from app.workers.runner.utilities import normalize_for_settings, safe_media_url
from app.workers.runner.workspace import TaskWorkspace

_MAX_PROBE_SAMPLE_ATTEMPTS = 8
_MAX_DURATION_PROBE_ATTEMPTS = 4


class RunnerInspectionPipeline:
    def __init__(
        self,
        settings: RunnerSettings,
        commands: MediaCommands,
        *,
        browser: BrowserRuntime | None = None,
    ) -> None:
        self.browser = browser
        self._settings = settings
        self._commands = commands

    def with_context(self, ctx: RunContext) -> RunnerInspectionPipeline:
        result = copy(self)
        result._commands = self._commands.with_context(ctx)
        return result

    def with_client(self, client: str) -> RunnerInspectionPipeline:
        result = copy(self)
        result._commands = self._commands.with_client(client)
        return result

    async def inspect(
        self,
        source: ProviderRequest,
        workspace: TaskWorkspace,
        *,
        context: ExecutionContext,
        cookie_jar: Path | None,
    ) -> MediaInspection:
        probe_failures: list[RunnerFailure] = []
        try:
            return await self._inspect(
                source,
                workspace,
                context=context,
                cookie_jar=cookie_jar,
                probe_failures=probe_failures,
            )
        except RunnerFailure as error:
            if (
                error.code in {"format_unavailable", "inspection_failed"}
                and probe_failures
            ):
                raise probe_failures[-1].attributed_to(context) from error
            if error.failure.phase is FailurePhase.RECOGNIZE:
                error.during(FailurePhase.FETCH_METADATA)
            error.attributed_to(context)
            raise

    async def _inspect(
        self,
        source: ProviderRequest,
        workspace: TaskWorkspace,
        *,
        context: ExecutionContext,
        cookie_jar: Path | None,
        probe_failures: list[RunnerFailure],
    ) -> MediaInspection:
        probed_formats: set[int] = set()
        sampled_formats: set[int] = set()
        payload = await self._commands.inspect(
            source, workspace.path, cookie_jar=cookie_jar
        )
        _require_generic_source_identity(source, payload)
        failure_context = _failure_context(source, context)
        payload = normalize_media_payload(
            payload, max_assets=self._settings.runner_max_gallery_assets
        )
        enforce_media_rights(
            payload,
            provider_key=context.provider_key,
        )
        payload = normalize_selected_format_metadata(payload)
        if payload.get("media_kind") in {"image_gallery", "video_collection"} or (
            str(payload.get("_type") or "").casefold() in {"playlist", "multi_video"}
            or isinstance(payload.get("entries"), list)
        ):
            return normalize_for_settings(payload, self._settings)
        if source.profile.probe_media_duration:
            payload = await self._probe_authoritative_duration(
                payload,
                source,
                workspace,
                failure_context=failure_context,
                probe_failures=probe_failures,
            )
        if payload.get("direct") is True and cookie_jar is None:
            probe = await self._commands.probe_remote(
                source.source_url,
                workspace.path,
                referer=source.source_url,
                failure_context=failure_context,
            )
            payload = enrich_direct_metadata(payload, probe)
        duration = payload.get("duration")
        if _positive_seconds(duration) is None:
            payload = await self._enrich_sparse_formats(
                payload,
                workspace,
                referer=source.source_url,
                cookie_jar=cookie_jar,
                probe_authenticated_media=source.profile.probe_authenticated_media,
                failure_context=failure_context,
                probe_failures=probe_failures,
                probed_formats=probed_formats,
            )
            duration = payload.get("duration")
            if _positive_seconds(duration) is None:
                payload = await self._enrich_from_probe_sample(
                    payload,
                    source,
                    workspace,
                    cookie_jar=cookie_jar,
                    failure_context=failure_context,
                    probe_failures=probe_failures,
                    sampled_formats=sampled_formats,
                )
        formats = payload.get("formats")
        if isinstance(formats, list) and any(_unknown_audio(raw) for raw in formats):
            # Missing codec metadata is not evidence that advertised audio is
            # absent. Resolve only those tracks before accepting silent video.
            payload = await self._enrich_sparse_formats(
                payload,
                workspace,
                referer=source.source_url,
                cookie_jar=cookie_jar,
                probe_authenticated_media=source.profile.probe_authenticated_media,
                unknown_audio_only=True,
                failure_context=failure_context,
                probe_failures=probe_failures,
                probed_formats=probed_formats,
            )
            streams = normalize_for_settings(payload, self._settings).streams
            if not any(stream.audio_codec_family is not None for stream in streams):
                raise RunnerFailure("format_unavailable", status=409)
        if source.profile.key in {"bilibili", "instagram", "twitch", "dailymotion"}:
            # Instagram can omit audio metadata on muxed videos; Twitch and
            # Bilibili can advertise rates different from the actual stream.
            # Dailymotion's selected 60 fps track must not supply the rate of
            # lower-quality tracks that omit FRAME-RATE in the master.
            # Resolve each bounded representation before confirming the plan.
            payload = await self._enrich_sparse_formats(
                payload,
                workspace,
                referer=source.source_url,
                cookie_jar=cookie_jar,
                probe_authenticated_media=source.profile.probe_authenticated_media,
                failure_context=failure_context,
                probe_failures=probe_failures,
                probed_formats=probed_formats,
            )
        payload = await self._enrich_sparse_formats(
            payload,
            workspace,
            referer=source.source_url,
            cookie_jar=cookie_jar,
            probe_authenticated_media=source.profile.probe_authenticated_media,
            failure_context=failure_context,
            probe_failures=probe_failures,
            unknown_video_only=True,
            probed_formats=probed_formats,
        )
        inspection = self._usable_inspection(payload)
        if inspection is not None:
            if _unresolved_video_formats(payload):
                sampled = await self._enrich_from_probe_sample(
                    payload,
                    source,
                    workspace,
                    cookie_jar=cookie_jar,
                    failure_context=failure_context,
                    probe_failures=probe_failures,
                    unresolved_video_only=True,
                    sampled_formats=sampled_formats,
                )
                inspection = self._usable_inspection(sampled) or inspection
            return inspection
        enriched = await self._enrich_sparse_formats(
            payload,
            workspace,
            referer=source.source_url,
            cookie_jar=cookie_jar,
            probe_authenticated_media=source.profile.probe_authenticated_media,
            failure_context=failure_context,
            probe_failures=probe_failures,
            probed_formats=probed_formats,
        )
        inspection = self._usable_inspection(enriched)
        if inspection is not None:
            return inspection
        sampled = await self._enrich_from_probe_sample(
            enriched,
            source,
            workspace,
            cookie_jar=cookie_jar,
            failure_context=failure_context,
            probe_failures=probe_failures,
            sampled_formats=sampled_formats,
        )
        inspection = self._usable_inspection(sampled)
        if inspection is None:
            raise RunnerFailure("format_unavailable", status=409)
        return inspection

    async def _probe_authoritative_duration(
        self,
        payload: dict[str, object],
        source: ProviderRequest,
        workspace: TaskWorkspace,
        *,
        failure_context: ProviderFailureContext,
        probe_failures: list[RunnerFailure],
    ) -> dict[str, object]:
        formats = payload.get("formats")
        if not isinstance(formats, list):
            raise RunnerFailure("format_unavailable", status=409)

        attempts = 0
        for index, value in enumerate(formats):
            if not isinstance(value, dict) or not isinstance(value.get("url"), str):
                continue
            attempts += 1
            try:
                media_url = safe_media_url(value["url"])
                probe = await self._commands.probe_remote(
                    media_url,
                    workspace.path,
                    referer=source.source_url,
                    failure_context=failure_context,
                )
                duration = _probe_duration(probe)
            except RunnerFailure as exc:
                exc.during(FailurePhase.PROBE_MEDIA)
                if not _is_soft_probe_failure(exc):
                    raise
                probe_failures.append(exc)
                duration = None
            except ValueError:
                duration = None
            if duration is not None:
                enriched_formats = list(formats)
                enriched_formats[index] = enrich_format_metadata(
                    value, probe, remote_probe=True
                )
                enriched_payload = dict(payload)
                enriched_payload["formats"] = enriched_formats
                enriched_payload["duration"] = duration
                return enriched_payload
            if attempts == _MAX_DURATION_PROBE_ATTEMPTS:
                break
        if probe_failures:
            raise probe_failures[-1]
        raise RunnerFailure(
            "media_probe_failed", status=502, cause_code="invalid_inspection_response"
        )

    def _usable_inspection(self, payload: dict[str, object]) -> MediaInspection | None:
        try:
            inspection = normalize_for_settings(payload, self._settings)
        except RunnerFailure as exc:
            if exc.code != "format_unavailable":
                raise
            return None
        return (
            inspection
            if build_download_options(inspection.streams, max_options=1)
            else None
        )

    async def _enrich_sparse_formats(
        self,
        payload: dict[str, object],
        workspace: TaskWorkspace,
        *,
        referer: str,
        cookie_jar: Path | None,
        probe_authenticated_media: bool,
        unknown_audio_only: bool = False,
        failure_context: ProviderFailureContext,
        probe_failures: list[RunnerFailure],
        unknown_video_only: bool = False,
        probed_formats: set[int] | None = None,
    ) -> dict[str, object]:
        if cookie_jar is not None and not probe_authenticated_media:
            return payload
        formats = payload.get("formats")
        if not isinstance(formats, list):
            return payload
        candidates: list[tuple[int, dict[str, object], str]] = []
        probed_formats = probed_formats if probed_formats is not None else set()
        for index, value in enumerate(formats):
            if not isinstance(value, dict):
                continue
            if unknown_audio_only and not _unknown_audio(value):
                continue
            if index in probed_formats or (
                unknown_video_only and not _unknown_video(value)
            ):
                continue
            url = value.get("url")
            if payload.get("_framefetch_full_stream") is True:
                url = value.get("_framefetch_probe_url", url)
            if isinstance(url, str):
                candidates.append((index, value, url))
        candidates.sort(key=lambda item: _probe_priority(item[1]))
        candidates = candidates[: max(0, 12 - len(probed_formats))]
        probed_formats.update(index for index, _, _ in candidates)
        semaphore = asyncio.Semaphore(4)

        async def enrich(
            index: int,
            raw: dict[str, object],
            url: str,
        ) -> tuple[int, dict[str, object], float | None]:
            try:
                media_url = safe_media_url(url)
                async with semaphore:
                    prefix = (
                        payload.get("_framefetch_full_stream") is True
                        and raw.get("_framefetch_probe_url") == url
                    )
                    probe_command = (
                        self._commands.probe_remote_prefix
                        if prefix
                        else self._commands.probe_remote
                    )
                    probe = await probe_command(
                        media_url,
                        workspace.path,
                        referer=referer,
                        failure_context=failure_context,
                    )
                return (
                    index,
                    enrich_format_metadata(
                        raw,
                        probe,
                        allow_nominal_fps=prefix,
                        remote_probe=not prefix,
                    ),
                    _probe_duration(probe),
                )
            except RunnerFailure as exc:
                exc.during(FailurePhase.PROBE_MEDIA)
                if not _is_soft_probe_failure(exc):
                    raise
                probe_failures.append(exc)
                return index, raw, None
            except ValueError:
                return index, raw, None

        results = await asyncio.gather(
            *(enrich(index, raw, url) for index, raw, url in candidates)
        )
        enriched_formats = list(formats)
        probed_duration: float | None = None
        for index, enriched, duration in results:
            enriched_formats[index] = enriched
            if probed_duration is None and duration is not None:
                probed_duration = duration
        enriched_payload = dict(payload)
        enriched_payload["formats"] = enriched_formats
        if (
            probed_duration is not None
            and payload.get("_framefetch_full_stream") is not True
            and not unknown_audio_only
            and _positive_seconds(payload.get("duration")) is None
        ):
            enriched_payload["duration"] = probed_duration
        return enriched_payload

    async def _enrich_from_probe_sample(
        self,
        payload: dict[str, object],
        source: ProviderRequest,
        workspace: TaskWorkspace,
        *,
        cookie_jar: Path | None,
        failure_context: ProviderFailureContext,
        probe_failures: list[RunnerFailure],
        sampled_formats: set[int],
        unresolved_video_only: bool = False,
    ) -> dict[str, object]:
        formats = payload.get("formats")
        if not isinstance(formats, list):
            return payload
        candidates: list[tuple[int, dict[str, object], int | None]] = []
        unresolved = (
            _unresolved_video_formats(payload) if unresolved_video_only else None
        )
        for index, value in enumerate(formats):
            if not isinstance(value, dict):
                continue
            if index in sampled_formats or (
                unresolved is not None and index not in unresolved
            ):
                continue
            provider_id = value.get("format_id")
            size = value.get("filesize") or value.get("filesize_approx")
            if not isinstance(provider_id, str):
                continue
            if size is None:
                candidates.append((index, value, None))
                continue
            if isinstance(size, (int, float)):
                size_bytes = int(size)
                if 0 < size_bytes <= self._settings.runner_max_probe_sample_bytes:
                    candidates.append((index, value, size_bytes))
        candidates.sort(
            key=lambda item: (
                *_probe_priority(item[1]),
                item[2] is None,
                item[2] if item[2] is not None else 0,
            )
        )
        sampled = dict(payload)
        enriched_formats = list(formats)
        for index, raw, _ in candidates[
            : max(0, _MAX_PROBE_SAMPLE_ATTEMPTS - len(sampled_formats))
        ]:
            sampled_formats.add(index)
            try:
                with TemporaryDirectory(
                    prefix="format-probe-",
                    dir=workspace.path,
                ) as directory:
                    probe_workspace = Path(directory)
                    output = probe_workspace / "sample.input"
                    await self._commands.download_probe_sample(
                        source,
                        str(raw["format_id"]),
                        output,
                        probe_workspace,
                        cookie_jar=cookie_jar,
                    )
                    probe = await self._commands.probe(
                        output,
                        probe_workspace,
                        failure_context=failure_context,
                    )
                enriched_formats[index] = enrich_format_metadata(raw, probe)
                sampled["formats"] = enriched_formats
                probed_duration = _probe_duration(probe)
                if (
                    probed_duration is not None
                    and payload.get("_framefetch_full_stream") is not True
                    and _positive_seconds(sampled.get("duration")) is None
                ):
                    sampled["duration"] = probed_duration
                if (
                    _positive_seconds(sampled.get("duration")) is not None
                    and self._usable_inspection(sampled) is not None
                    and (
                        not unresolved_video_only
                        or not _unresolved_video_formats(sampled)
                    )
                ):
                    return sampled
            except RunnerFailure as exc:
                exc.during(FailurePhase.PROBE_MEDIA)
                if not _is_soft_probe_failure(exc):
                    raise
                probe_failures.append(exc)
                continue
            except OSError as exc:
                raise RunnerFailure(
                    "runner_dependency_unavailable",
                    status=503,
                    phase=FailurePhase.PROBE_MEDIA,
                ) from exc
        return sampled


def _require_generic_source_identity(
    source: ProviderRequest, payload: dict[str, object]
) -> None:
    """Keep a long-tail extractor from crossing a registered route or deny rule."""
    if source.profile.key != "generic":
        return
    if (
        payload.get("media_kind") in {"image_gallery", "video_collection"}
        or payload.get("entries") is not None
        or "section_start" in payload
        or "section_end" in payload
        or str(payload.get("_type") or "").casefold()
        in {"playlist", "multi_video", "url", "url_transparent"}
    ):
        # Member URLs can cross a disabled Provider. In yt-dlp's transparent
        # clip merge, section bounds let the outer extractor key mask the inner
        # Provider key, so even a single clipped video is not attested here.
        raise RunnerFailure("provider_unsupported", status=422)
    webpage_url = payload.get("webpage_url")
    extractor_key = payload.get("extractor_key")
    if not isinstance(webpage_url, str) or not isinstance(extractor_key, str):
        raise RunnerFailure("provider_unsupported", status=422)
    final_url = safe_media_url(webpage_url)
    if current_provider_registry().resolve(final_url).key != "generic":
        raise RunnerFailure("provider_unsupported", status=422)
    # GenericIE can follow arbitrary embeds and redirects without proving the
    # final platform. Named upstream extractors must claim the original URL.
    if extractor_key in {"Generic", "PeerTube"}:
        raise RunnerFailure("provider_unsupported", status=422)
    from yt_dlp.extractor import get_info_extractor  # type: ignore[import-untyped]

    try:
        extractor = get_info_extractor(extractor_key)
    except KeyError:
        # Project plugin keys are intentionally not loaded into this process;
        # an opaque key could represent an embedded registered Provider.
        raise RunnerFailure("provider_unsupported", status=422) from None
    else:
        if not extractor.suitable(source.source_url):
            raise RunnerFailure("provider_unsupported", status=422)


def _unknown_audio(raw: object) -> bool:
    return (
        isinstance(raw, dict)
        and raw.get("vcodec") == "none"
        and raw.get("acodec") in (None, "")
    )


def _failure_context(
    source: ProviderRequest,
    context: ExecutionContext,
) -> ProviderFailureContext:
    return ProviderFailureContext(
        provider_key=source.profile.key,
        source_url=source.source_url,
        authenticated=context.identity_used,
    )


def _is_soft_probe_failure(error: RunnerFailure) -> bool:
    return error.code in {"inspection_failed", "media_probe_failed"}


def _probe_duration(probe: dict[str, object]) -> float | None:
    format_info = probe.get("format")
    if not isinstance(format_info, dict):
        return None
    return _positive_seconds(format_info.get("duration"))


def _positive_seconds(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        duration = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return duration if math.isfinite(duration) and duration > 0 else None


def _unknown_video(raw: object) -> bool:
    return (
        isinstance(raw, dict)
        and raw.get("vcodec") != "none"
        and (
            raw.get("vcodec") in (None, "")
            or any(
                _positive_seconds(raw.get(key)) is None
                for key in ("fps", "width", "height")
            )
        )
    )


def _probe_priority(raw: dict[str, object]) -> tuple[bool, float, float]:
    return (
        raw.get("vcodec") == "none",
        -(_positive_seconds(raw.get("height")) or 0),
        -(_positive_seconds(raw.get("width")) or 0),
    )


def _unresolved_video_formats(payload: dict[str, object]) -> set[int]:
    formats = payload.get("formats")
    if not isinstance(formats, list):
        return set()
    known_dimensions = {
        (_positive_seconds(raw.get("width")), _positive_seconds(raw.get("height")))
        for raw in formats
        if isinstance(raw, dict)
        and raw.get("vcodec") not in (None, "", "none")
        and not _unknown_video(raw)
    }
    return {
        index
        for index, raw in enumerate(formats)
        if _unknown_video(raw)
        and isinstance(raw, dict)
        and (_positive_seconds(raw.get("width")), _positive_seconds(raw.get("height")))
        not in known_dimensions
    }
