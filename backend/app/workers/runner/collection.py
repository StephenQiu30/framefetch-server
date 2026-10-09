"""Bounded ZIP assembly for yt-dlp video collections."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from app.services.provider_failures import FailurePhase
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.gallery import download_gallery_zip
from app.workers.runner.metadata import GalleryAsset
from app.workers.runner.verification import verify_collection_video
from app.workers.runner.workspace import TaskWorkspace


async def download_video_collection_zip(
    source: object,
    output: Path,
    workspace: TaskWorkspace,
    *,
    expected_count: int,
    title: str,
    referer: str,
    commands: object,
    max_video_bytes: int,
    max_duration_seconds: float,
    max_assets: int,
    cookie_jar: Path | None,
    fallback_assets: tuple[GalleryAsset, ...] = (),
) -> int:
    """Download each playlist member, then package every member.

    Some providers expose an image carousel as a playlist with no playable
    video formats. In that case, use the validated image assets supplied by
    inspection instead of forcing a video format selection.
    """
    if not 1 <= expected_count <= max_assets:
        raise RunnerFailure("format_limit_exceeded", status=413)
    download = getattr(commands, "download_collection", None)
    probe = getattr(commands, "probe", None)
    decode = getattr(commands, "verify_full_decode", None)
    if not callable(download) or not callable(probe) or not callable(decode):
        raise RunnerFailure("runner_dependency_unavailable", status=503)

    output_dir = workspace.path / "collection-output"
    output_dir.mkdir(mode=0o700)
    files: list[tuple[Path, str]] = []
    completed = False
    try:
        try:
            await download(
                source,
                output_dir,
                workspace.path,
                max_bytes=max_video_bytes,
                max_entries=max_assets + 1,
                cookie_jar=cookie_jar,
            )
        except RunnerFailure as exc:
            if (
                exc.code != "format_unavailable"
                or len(fallback_assets) != expected_count
            ):
                raise
            count = await download_gallery_zip(
                fallback_assets,
                output,
                workspace,
                title=title,
                referer=referer,
                commands=commands,
                max_asset_bytes=max_video_bytes,
                max_assets=max_assets,
            )
            completed = True
            return count
        workspace.validate_usage()
        downloaded = _files(output_dir)
        if len(downloaded) != expected_count:
            raise RunnerFailure("source_changed", status=409)
        for index, path in enumerate(downloaded, start=1):
            verified = verify_collection_video(
                await probe(path, workspace.path, phase=FailurePhase.VALIDATE),
                max_duration=max_duration_seconds,
                source_extension=path.suffix,
            )
            await decode(path, workspace.path)
            files.append((path, f"videos/{index:04d}.{verified.extension}"))

        with zipfile.ZipFile(
            output, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "title": title,
                        "media_kind": "video_collection",
                        "asset_count": len(files),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
            for path, name in files:
                archive.write(path, name)
        workspace.validate_usage()
        completed = True
        return len(files)
    finally:
        if not completed:
            output.unlink(missing_ok=True)
        shutil.rmtree(output_dir, ignore_errors=True)


def _files(directory: Path) -> list[Path]:
    candidates = sorted(directory.iterdir(), key=lambda path: path.name)
    if any(path.is_symlink() or not path.is_file() for path in candidates):
        raise RunnerFailure("invalid_artifact", status=422)
    return candidates
