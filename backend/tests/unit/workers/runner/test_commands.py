from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import httpx
import pytest
from app.services.downloads.rules.enums import Container
from app.services.provider_types import ProviderAccessMode
from app.workers.runner import commands as commands_module
from app.workers.runner.commands import MediaCommands
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.process import ProcessResult
from app.workers.runner.provider_errors import ProviderFailureContext
from app.workers.runner.yt_dlp_commands import YtDlpCommandBuilder
from helpers import settings
from test_provider_sessions import session_settings


class FailingSupervisor:
    def __init__(self, stderr: bytes) -> None:
        self.stderr = stderr

    async def run(
        self,
        _argv: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        del cwd, timeout_seconds, env
        return ProcessResult(1, b"", self.stderr, False, False)


class RecordingSupervisor:
    def __init__(self) -> None:
        self.argv: Sequence[str] = ()
        self.env: Mapping[str, str] = {}

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        del cwd, timeout_seconds
        self.argv = argv
        self.env = env or {}
        return ProcessResult(0, b"{}", b"", False, False)


class SuccessfulWarningSupervisor:
    def __init__(self, stdout: bytes, stderr: bytes) -> None:
        self.stdout = stdout
        self.stderr = stderr

    async def run(
        self,
        _argv: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        del cwd, timeout_seconds, env
        return ProcessResult(0, self.stdout, self.stderr, False, False)


@pytest.mark.asyncio
async def test_mp4_remux_moves_metadata_before_media_for_streaming(
    tmp_path: Path,
) -> None:
    supervisor = RecordingSupervisor()
    commands = MediaCommands(settings(tmp_path), supervisor)

    await commands.remux(
        (tmp_path / "video.input", tmp_path / "audio.input"),
        tmp_path / "artifact.mp4",
        Container.MP4,
        tmp_path,
    )

    assert supervisor.argv[supervisor.argv.index("-movflags") + 1] == "+faststart"


@pytest.mark.asyncio
async def test_webm_remux_does_not_use_mp4_faststart_flag(tmp_path: Path) -> None:
    supervisor = RecordingSupervisor()
    commands = MediaCommands(settings(tmp_path), supervisor)

    await commands.remux(
        (tmp_path / "video.input", tmp_path / "audio.input"),
        tmp_path / "artifact.webm",
        Container.WEBM,
        tmp_path,
    )

    assert "-movflags" not in supervisor.argv


@pytest.mark.asyncio
async def test_silent_remux_does_not_require_an_audio_stream(tmp_path: Path) -> None:
    supervisor = RecordingSupervisor()
    commands = MediaCommands(settings(tmp_path), supervisor)

    await commands.remux(
        (tmp_path / "video.input",),
        tmp_path / "silent.mp4",
        Container.MP4,
        tmp_path,
        include_audio=False,
    )

    assert "0:v:0" in supervisor.argv
    assert "0:a:0" not in supervisor.argv
    assert "1:a:0" not in supervisor.argv


def test_provider_retry_budget_applies_to_inspect_and_download(tmp_path: Path) -> None:
    builder = YtDlpCommandBuilder(settings(tmp_path), tmp_path)
    commands = (
        builder.inspect(
            "https://www.youtube.com/watch?v=owned",
            cookie_jar=None,
        ).argv,
        builder.download(
            "https://www.youtube.com/watch?v=owned",
            "18",
            tmp_path / "youtube.mp4",
            max_bytes=1024,
            cookie_jar=None,
        ).argv,
        builder.inspect("https://vimeo.com/76979871", cookie_jar=None).argv,
        builder.download(
            "https://vimeo.com/76979871",
            "http-540p",
            tmp_path / "vimeo.mp4",
            max_bytes=1024,
            cookie_jar=None,
        ).argv,
    )

    for command, expected in zip(commands, ("0", "0", "3", "3"), strict=True):
        assert "--no-warnings" not in command
        for option in ("--retries", "--fragment-retries", "--extractor-retries"):
            assert command.count(option) == 1
            assert command[command.index(option) + 1] == expected

    assert "--ignore-no-formats-error" in commands[0]
    assert "--ignore-no-formats-error" in commands[2]
    assert "--ignore-no-formats-error" not in commands[1]
    assert "--ignore-no-formats-error" not in commands[3]


def test_probe_download_can_disable_ytdlp_cache(tmp_path: Path) -> None:
    builder = YtDlpCommandBuilder(settings(tmp_path), tmp_path)

    command = builder.download(
        "https://vimeo.com/76979871",
        "http-540p",
        tmp_path / "probe.mp4",
        max_bytes=8 * 1024**2,
        cookie_jar=None,
        disable_cache=True,
    ).argv

    assert command.count("--no-cache-dir") == 1


def test_collection_download_enables_playlist_with_bounded_output(
    tmp_path: Path,
) -> None:
    builder = YtDlpCommandBuilder(settings(tmp_path), tmp_path)

    command = builder.download_collection(
        "https://www.instagram.com/p/example/",
        tmp_path / "collection",
        max_bytes=1024,
        max_entries=11,
        cookie_jar=None,
    ).argv

    assert "--yes-playlist" in command
    assert "--no-playlist" not in command
    assert command[command.index("--playlist-end") + 1] == "11"
    assert command[command.index("--max-filesize") + 1] == "1024"
    assert command[-1] == "https://www.instagram.com/p/example/"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("authenticated", "expected_code", "expected_status"),
    (
        (False, "guest_context_required", 503),
        (True, "credential_expired", 422),
    ),
)
async def test_douyin_fresh_cookie_hint_distinguishes_session_contexts(
    tmp_path: Path,
    authenticated: bool,
    expected_code: str,
    expected_status: int,
) -> None:
    commands = MediaCommands(
        session_settings(tmp_path) if authenticated else settings(tmp_path),
        FailingSupervisor(
            b"ERROR: Fresh cookies (not necessarily logged in) are needed"
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect(
            "https://www.douyin.com/video/123",
            tmp_path,
            cookie_jar=tmp_path / "cookies.txt" if authenticated else None,
        )

    assert caught.value.code == expected_code
    assert caught.value.status == expected_status


@pytest.mark.asyncio
async def test_explicit_rate_limit_precedes_ambiguous_login_hint(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(
            b"WARNING: rate-limit reached or login required\n"
            b"ERROR: HTTP Error 429: Too Many Requests"
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://x.com/example/status/123", tmp_path)

    assert caught.value.code == "provider_rate_limited"
    assert caught.value.status == 429


@pytest.mark.asyncio
async def test_ambiguous_rate_limit_or_login_hint_is_temporary(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: rate-limit reached or login required"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://x.com/example/status/123", tmp_path)

    assert caught.value.code == "provider_temporarily_unavailable"
    assert caught.value.status == 503


@pytest.mark.asyncio
async def test_public_instagram_empty_response_does_not_request_account_session(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(
            b"WARNING: Instagram API is not granting access\n"
            b"ERROR: Instagram sent an empty media response. "
            b"Use --cookies-from-browser or --cookies"
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://www.instagram.com/p/example/", tmp_path)

    assert caught.value.code == "provider_temporarily_unavailable"
    assert caught.value.status == 503


@pytest.mark.asyncio
async def test_bilibili_412_is_classified_as_an_egress_challenge(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(
            b"ERROR: [BiliBili] fixture: HTTP Error 412: Precondition Failed"
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect(
            "https://www.bilibili.com/video/BV13x41117TL",
            tmp_path,
        )

    assert caught.value.code == "egress_challenged"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_instagram_missing_video_formats_is_not_retried_as_temporary_failure(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: [Instagram] No video formats found!"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.download_collection(
            "https://www.instagram.com/p/example/",
            tmp_path / "collection",
            tmp_path,
            max_bytes=1024,
            max_entries=2,
        )

    assert caught.value.code == "format_unavailable"
    assert caught.value.status == 409


@pytest.mark.asyncio
async def test_inspection_classifies_youtube_bot_confirmation_requirement(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(
            b"WARNING: HTTP Error 429: Too Many Requests\n"
            b"ERROR: Sign in to confirm you're not a bot. "
            b"Use --cookies for authentication"
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://www.youtube.com/watch?v=owned", tmp_path)

    assert caught.value.code == "egress_challenged"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_successful_youtube_process_with_bot_warning_and_no_formats_is_challenged(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        SuccessfulWarningSupervisor(
            b'{"id":"owned","formats":[]}',
            b"WARNING: Sign in to confirm you're not a bot. "
            b"Use --cookies for authentication",
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://www.youtube.com/watch?v=owned", tmp_path)

    assert caught.value.code == "egress_challenged"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_successful_youtube_process_keeps_usable_media_despite_warning(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        SuccessfulWarningSupervisor(
            b'{"id":"owned","formats":[{"url":"https://media.example/video"}]}',
            b"WARNING: Sign in to confirm you're not a bot. "
            b"Use --cookies for authentication",
        ),
    )

    payload = await commands.inspect(
        "https://www.youtube.com/watch?v=owned",
        tmp_path,
    )

    assert payload["id"] == "owned"


@pytest.mark.asyncio
async def test_authenticated_youtube_bot_confirmation_is_egress_challenge(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        session_settings(tmp_path),
        FailingSupervisor(
            b"ERROR: Sign in to confirm you're not a bot. "
            b"Use --cookies for authentication"
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect(
            "https://www.youtube.com/watch?v=owned",
            tmp_path,
            cookie_jar=tmp_path / "cookies.txt",
        )

    assert caught.value.code == "egress_challenged"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_authenticated_cookie_rotation_failure_is_expired_session(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        session_settings(tmp_path),
        FailingSupervisor(b"ERROR: Fresh cookies are needed"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect(
            "https://www.youtube.com/watch?v=owned",
            tmp_path,
            cookie_jar=tmp_path / "cookies.txt",
        )

    assert caught.value.code == "credential_expired"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_wechat_missing_public_media_is_reported_as_restricted_content(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: WeChat Channels public media is not downloadable"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect(
            "https://weixin.qq.com/sph/AFWYoXF5Bw",
            tmp_path,
        )

    assert caught.value.code == "content_entitlement_unknown"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_inspection_classifies_unavailable_youtube_video(tmp_path: Path) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: [youtube] pqyXR30AoOs: Video unavailable"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://youtu.be/pqyXR30AoOs", tmp_path)

    assert caught.value.code == "provider_link_unavailable"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_youtube_rate_limit_precedes_unavailable_fallback(tmp_path: Path) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(
            b"WARNING: HTTP Error 429: Too Many Requests\n"
            b"ERROR: [youtube] owned: This video is unavailable"
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://www.youtube.com/watch?v=owned", tmp_path)

    assert caught.value.code == "provider_rate_limited"
    assert caught.value.status == 429


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("terminal_error", "expected_code", "expected_status"),
    (
        (b"ERROR: This video is DRM protected", "drm_protected", 422),
        (b"ERROR: This video is private", "content_private", 403),
        (
            b"ERROR: This video is not available in your country",
            "provider_geo_restricted",
            422,
        ),
        (
            b"ERROR: Account cookies are no longer valid",
            "credential_expired",
            422,
        ),
        (b"ERROR: Fresh cookies are needed", "provider_session_not_ready", 503),
    ),
)
async def test_youtube_terminal_failure_precedes_rate_limit_warning(
    tmp_path: Path,
    terminal_error: bytes,
    expected_code: str,
    expected_status: int,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(
            b"WARNING: HTTP Error 429: Too Many Requests\n" + terminal_error
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://www.youtube.com/watch?v=owned", tmp_path)

    assert caught.value.code == expected_code
    assert caught.value.status == expected_status


@pytest.mark.asyncio
async def test_tiktok_rate_limit_precedes_temporary_api_failure(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(
            b"WARNING: HTTP Error 429: Too Many Requests\n"
            b"ERROR: TikTok official player API temporarily unavailable"
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect(
            "https://www.tiktok.com/@creator/video/6742501081818877190",
            tmp_path,
        )

    assert caught.value.code == "provider_rate_limited"
    assert caught.value.status == 429


@pytest.mark.asyncio
async def test_inspection_classifies_vimeo_login_requirement(tmp_path: Path) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(
            b"ERROR: The Vimeo extractor only works when logged-in. Use --cookies"
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://vimeo.com/76979871", tmp_path)

    assert caught.value.code == "credential_required"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_vimeo_inspection_checks_real_format_downloadability(
    tmp_path: Path,
) -> None:
    supervisor = RecordingSupervisor()
    commands = MediaCommands(settings(tmp_path), supervisor)

    await commands.inspect("https://vimeo.com/76979871", tmp_path)

    assert "--check-formats" in supervisor.argv
    assert supervisor.argv[-1] == "https://player.vimeo.com/video/76979871"


@pytest.mark.asyncio
async def test_download_classifies_selected_drm_format(tmp_path: Path) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(
            b"ERROR: This format is DRM protected; Try selecting another format"
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.download_stream(
            "https://vimeo.com/76979871",
            "hls-video",
            tmp_path / "video.input",
            tmp_path,
        )

    assert caught.value.code == "drm_protected"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_inspection_classifies_unavailable_tiktok_player(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(
            b"ERROR: TikTok video not available from the official player"
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect(
            "https://www.tiktok.com/@creator/video/123",
            tmp_path,
        )

    assert caught.value.code == "provider_link_unavailable"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_inspection_classifies_tiktok_player_api_outage(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: TikTok official player API temporarily unavailable"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect(
            "https://www.tiktok.com/@creator/video/123",
            tmp_path,
        )

    assert caught.value.code == "provider_temporarily_unavailable"
    assert caught.value.status == 503


@pytest.mark.asyncio
async def test_inspection_classifies_tiktok_player_schema_regression(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: TikTok official player response structure changed"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect(
            "https://www.tiktok.com/@creator/video/123",
            tmp_path,
        )

    assert caught.value.code == "extractor_regression"
    assert caught.value.status == 502


@pytest.mark.asyncio
async def test_anonymous_youtube_media_403_is_an_egress_challenge(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(
            b"ERROR: unable to download video data: HTTP Error 403: Forbidden"
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.download_stream(
            "https://www.youtube.com/watch?v=owned",
            "401",
            tmp_path / "video.input",
            tmp_path,
        )

    assert caught.value.code == "egress_challenged"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_explicit_youtube_pot_rejection_keeps_specific_diagnosis(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: PO Token rejected: HTTP Error 403: Forbidden"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.download_stream(
            "https://www.youtube.com/watch?v=owned",
            "401",
            tmp_path / "video.input",
            tmp_path,
        )

    assert caught.value.code == "pot_rejected"
    assert caught.value.status == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stderr",
    (
        b"WARNING: Error reaching GET http://youtube-pot-provider:4416/ping "
        b"(caused by TransportError). Please make sure that the server is reachable\n"
        b"ERROR: Sign in to confirm you're not a bot",
        b'PO Token Provider "bgutil:http" rejected this request; '
        b"bgutil:http server is not available",
    ),
)
async def test_bgutil_unreachable_stderr_keeps_specific_diagnosis(
    tmp_path: Path,
    stderr: bytes,
) -> None:
    commands = MediaCommands(settings(tmp_path), FailingSupervisor(stderr))

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect(
            "https://www.youtube.com/watch?v=owned",
            tmp_path,
        )

    assert caught.value.code == "pot_provider_unavailable"
    assert caught.value.status == 503


@pytest.mark.asyncio
async def test_inspection_classifies_tiktok_post_ip_restriction(tmp_path: Path) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(
            b"ERROR: Your IP address is blocked from accessing this post"
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect(
            "https://www.tiktok.com/@creator/video/123",
            tmp_path,
        )

    assert caught.value.code == "provider_geo_restricted"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_expired_tiktok_short_link_is_reported_as_unavailable(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: Unsupported URL: https://www.tiktok.com/?_r=1"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://www.tiktok.com/t/expired", tmp_path)

    assert caught.value.code == "provider_link_unavailable"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_dead_x_card_domain_is_reported_as_unavailable(tmp_path: Path) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: HTTP Error 500: Domain Not Found"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect(
            "https://twitter.com/example/status/123",
            tmp_path,
        )

    assert caught.value.code == "provider_link_unavailable"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_inspection_classifies_reddit_account_requirement(tmp_path: Path) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: Account authentication is required. Use --cookies"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect(
            "https://www.reddit.com/r/example/comments/123",
            tmp_path,
        )

    assert caught.value.code == "credential_required"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_youtube_uses_operator_managed_provider_egress(tmp_path: Path) -> None:
    supervisor = RecordingSupervisor()
    configured = settings(tmp_path).model_copy(
        update={
            "runner_provider_egress_proxies": {"youtube": "http://youtube-egress:3128"}
        }
    )
    commands = MediaCommands(configured, supervisor)

    await commands.inspect("https://www.youtube.com/watch?v=owned", tmp_path)

    assert supervisor.argv[supervisor.argv.index("--proxy") + 1] == (
        "http://youtube-egress:3128"
    )
    assert supervisor.env["HTTPS_PROXY"] == "http://youtube-egress:3128"
    assert "--cookies" not in supervisor.argv
    assert "--no-warnings" not in supervisor.argv
    for option in ("--retries", "--fragment-retries", "--extractor-retries"):
        assert supervisor.argv[supervisor.argv.index(option) + 1] == "0"


@pytest.mark.asyncio
async def test_youtube_uses_service_managed_pot_without_cookies(tmp_path: Path) -> None:
    supervisor = RecordingSupervisor()
    probe_calls: list[tuple[str, str]] = []

    async def healthy_probe(base_url: str, expected_version: str) -> bool:
        probe_calls.append((base_url, expected_version))
        return True

    configured = settings(tmp_path).model_copy(
        update={
            "runner_youtube_pot_base_url": "http://youtube-pot-provider:4416",
            "runner_youtube_pot_provider_version": "bgutil-http-9.8.7",
        }
    )
    commands = MediaCommands(
        configured,
        supervisor,
        pot_provider_probe=healthy_probe,
    )

    await commands.inspect("https://www.youtube.com/watch?v=owned", tmp_path)

    assert probe_calls == [("http://youtube-pot-provider:4416", "9.8.7")]
    assert "youtube:player_client=mweb" in supervisor.argv
    assert all("mweb,default" not in item for item in supervisor.argv)
    assert (
        "youtubepot-bgutilhttp:base_url=http://youtube-pot-provider:4416"
        in supervisor.argv
    )
    assert "--cookies" not in supervisor.argv


@pytest.mark.asyncio
async def test_youtube_pot_preflight_fails_before_process_spawn(tmp_path: Path) -> None:
    supervisor = RecordingSupervisor()

    async def unavailable_probe(_base_url: str, _expected_version: str) -> bool:
        return False

    configured = settings(tmp_path).model_copy(
        update={
            "runner_youtube_pot_base_url": "http://youtube-pot-provider:4416",
        }
    )
    commands = MediaCommands(
        configured,
        supervisor,
        pot_provider_probe=unavailable_probe,
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://www.youtube.com/watch?v=owned", tmp_path)

    assert caught.value.code == "pot_provider_unavailable"
    assert caught.value.status == 503
    assert supervisor.argv == ()


@pytest.mark.asyncio
async def test_youtube_failure_rechecks_pot_after_process_spawn(tmp_path: Path) -> None:
    supervisor = FailingSupervisor(b"ERROR: Sign in to confirm you're not a bot")
    outcomes = iter((True, False))

    async def lifecycle_probe(_base_url: str, _expected_version: str) -> bool:
        return next(outcomes)

    configured = settings(tmp_path).model_copy(
        update={
            "runner_youtube_pot_base_url": "http://youtube-pot-provider:4416",
        }
    )
    commands = MediaCommands(
        configured,
        supervisor,
        pot_provider_probe=lifecycle_probe,
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://www.youtube.com/watch?v=owned", tmp_path)

    assert caught.value.code == "pot_provider_unavailable"
    assert caught.value.status == 503


@pytest.mark.asyncio
async def test_non_youtube_command_does_not_probe_pot_provider(tmp_path: Path) -> None:
    supervisor = RecordingSupervisor()

    async def unexpected_probe(_base_url: str, _expected_version: str) -> bool:
        raise AssertionError("non-YouTube commands cannot probe the POT provider")

    configured = settings(tmp_path).model_copy(
        update={
            "runner_youtube_pot_base_url": "http://youtube-pot-provider:4416",
        }
    )
    commands = MediaCommands(
        configured,
        supervisor,
        pot_provider_probe=unexpected_probe,
    )

    await commands.inspect("https://vimeo.com/123", tmp_path)

    assert supervisor.argv


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    (
        "timeout",
        "deadline",
        "invalid_json",
        "non_object_json",
        "wrong_version",
        "redirect",
    ),
)
async def test_pot_semantic_probe_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    options: dict[str, object] = {}

    class Client:
        def __init__(self, **kwargs: object) -> None:
            options.update(kwargs)

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get(self, url: str) -> httpx.Response:
            assert url == "http://youtube-pot-provider:4416/ping"
            if outcome == "timeout":
                raise httpx.ReadTimeout(
                    "timed out",
                    request=httpx.Request("GET", url),
                )
            if outcome == "deadline":
                raise TimeoutError
            if outcome == "invalid_json":
                return httpx.Response(200, content=b"not-json")
            if outcome == "non_object_json":
                return httpx.Response(200, json=[{"version": "1.3.2"}])
            if outcome == "wrong_version":
                return httpx.Response(200, json={"version": "1.3.1"})
            return httpx.Response(302, json={"version": "1.3.2"})

    monkeypatch.setattr(commands_module.httpx, "AsyncClient", Client)

    assert (
        await commands_module._pot_provider_ready(
            "http://youtube-pot-provider:4416",
            "1.3.2",
        )
        is False
    )
    assert options == {
        "timeout": 2.0,
        "trust_env": False,
        "follow_redirects": False,
    }


@pytest.mark.asyncio
async def test_pot_semantic_probe_accepts_only_exact_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get(self, _url: str) -> httpx.Response:
            return httpx.Response(200, json={"version": "1.3.2"})

    monkeypatch.setattr(commands_module.httpx, "AsyncClient", Client)

    assert await commands_module._pot_provider_ready(
        "http://youtube-pot-provider:4416",
        "1.3.2",
    )


@pytest.mark.asyncio
async def test_youtube_client_profile_does_not_depend_on_sidecar_url(
    tmp_path: Path,
) -> None:
    supervisor = RecordingSupervisor()
    commands = MediaCommands(settings(tmp_path), supervisor)

    await commands.inspect("https://www.youtube.com/watch?v=owned", tmp_path)

    assert "youtube:player_client=mweb" in supervisor.argv
    assert all("youtubepot-bgutilhttp" not in item for item in supervisor.argv)


@pytest.mark.asyncio
async def test_tiktok_public_player_command_has_no_browser_or_session_args(
    tmp_path: Path,
) -> None:
    supervisor = RecordingSupervisor()
    commands = MediaCommands(settings(tmp_path), supervisor)

    await commands.inspect(
        "https://www.tiktok.com/@creator/video/123",
        tmp_path,
    )

    assert "--cookies" not in supervisor.argv
    assert "--impersonate" not in supervisor.argv
    assert "--extractor-args" not in supervisor.argv
    assert supervisor.argv[-1] == "https://www.tiktok.com/@creator/video/123"


@pytest.mark.asyncio
async def test_tiktok_public_player_rejects_cookie_jar(tmp_path: Path) -> None:
    supervisor = RecordingSupervisor()
    commands = MediaCommands(settings(tmp_path), supervisor)

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect(
            "https://www.tiktok.com/@creator/video/123",
            tmp_path,
            cookie_jar=tmp_path / "operation.cookies.txt",
        )

    assert caught.value.code == "provider_session_not_allowed"
    assert supervisor.argv == ()


@pytest.mark.asyncio
async def test_non_allowlisted_provider_cannot_receive_cookie_jar(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(settings(tmp_path), RecordingSupervisor())

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect(
            "https://www.bilibili.com/video/BV1xx",
            tmp_path,
            cookie_jar=tmp_path / "operation.cookies.txt",
        )

    assert caught.value.code == "provider_session_not_allowed"


@pytest.mark.asyncio
async def test_session_runner_passes_jar_for_unlisted_sites(tmp_path: Path) -> None:
    # The broker admits any site with a deployment session, catalog or not.
    supervisor = RecordingSupervisor()
    commands = MediaCommands(session_settings(tmp_path), supervisor)
    jar = tmp_path / "operation.cookies.txt"

    await commands.inspect("https://media.example.co.uk/v/1", tmp_path, cookie_jar=jar)

    index = supervisor.argv.index("--cookies")
    assert supervisor.argv[index + 1] == str(jar)


@pytest.mark.asyncio
async def test_non_ytdlp_failures_keep_their_original_code(tmp_path: Path) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ffprobe exited with status 1"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.probe_remote("https://media.example/video", tmp_path)

    assert caught.value.code == "inspection_failed"
    assert caught.value.status == 502


@pytest.mark.asyncio
async def test_remote_probe_classifies_provider_failure_context(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: Sign in to confirm you're not a bot"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.probe_remote(
            "https://media.example/video",
            tmp_path,
            referer="https://www.youtube.com/watch?v=owned",
        )

    assert caught.value.code == "egress_challenged"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_remux_preserves_provider_failure_context(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: HTTP Error 403: Forbidden"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.remux(
            (tmp_path / "video.input",),
            tmp_path / "artifact.mp4",
            Container.MP4,
            tmp_path,
            include_audio=False,
            failure_context=ProviderFailureContext(
                provider_key="youtube",
                source_url="https://www.youtube.com/watch?v=owned",
                authenticated=False,
            ),
        )

    assert caught.value.code == "egress_challenged"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_douyin_short_link_that_redirects_to_home_is_classified_as_unavailable(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: Unsupported URL: https://www.douyin.com/"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://v.douyin.com/KWku50HECg/", tmp_path)

    assert caught.value.code == "provider_link_unavailable"
    assert caught.value.status == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stderr", "expected_code", "expected_status"),
    (
        (
            b"ERROR: Douyin official share link temporarily unavailable",
            "provider_temporarily_unavailable",
            503,
        ),
        (
            b"ERROR: Douyin official share link response structure changed",
            "extractor_regression",
            502,
        ),
        (
            b"ERROR: Douyin official share link verification required",
            "egress_challenged",
            422,
        ),
        (
            b"ERROR: Douyin official share link rate limited",
            "provider_rate_limited",
            429,
        ),
    ),
)
async def test_douyin_official_share_failures_keep_distinct_classifications(
    tmp_path: Path,
    stderr: bytes,
    expected_code: str,
    expected_status: int,
) -> None:
    commands = MediaCommands(settings(tmp_path), FailingSupervisor(stderr))

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://v.douyin.com/Tq0eYJRMYRk/", tmp_path)

    assert caught.value.code == expected_code
    assert caught.value.status == expected_status


@pytest.mark.asyncio
async def test_douyin_official_note_is_classified_as_media_unsupported(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(
            b"ERROR: Douyin official note is not a supported single video"
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://v.douyin.com/qao3WztsXns/", tmp_path)

    assert caught.value.code == "provider_media_unsupported"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_xhs_share_link_without_token_is_classified_as_unavailable(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: Unable to extract initial state"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://xhslink.com/m/expired", tmp_path)

    assert caught.value.code == "provider_link_unavailable"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_xhs_first_party_unavailable_note_is_not_an_extractor_regression(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: Xiaohongshu note unavailable"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect(
            "https://www.xiaohongshu.com/explore/6411f5d60000000013031939",
            tmp_path,
        )

    assert caught.value.code == "provider_link_unavailable"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_xhs_first_party_ip_risk_is_a_verification_failure(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: Xiaohongshu request verification required"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect(
            "https://www.xiaohongshu.com/explore/6411f5d60000000013031939",
            tmp_path,
        )

    assert caught.value.code == "egress_challenged"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_xhs_missing_video_formats_is_classified_as_extractor_regression(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: [xiaohongshu] 6411: No video formats found!"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect(
            "https://www.xiaohongshu.com/explore/6411f5d60000000013031939",
            tmp_path,
        )

    assert caught.value.code == "extractor_regression"
    assert caught.value.status == 502


@pytest.mark.asyncio
async def test_generic_unsupported_url_keeps_inspection_failure(tmp_path: Path) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: Unsupported URL: https://media.example/"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://media.example/video", tmp_path)

    assert caught.value.code == "inspection_failed"
    assert caught.value.status == 502


@pytest.mark.asyncio
async def test_wechat_channels_without_public_media_is_restricted(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: WeChat Channels public media is not downloadable"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://weixin.qq.com/sph/AFWYoXF5Bw", tmp_path)

    assert caught.value.code == "content_entitlement_unknown"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_kuaishou_expired_link_is_classified_as_unavailable(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: Kuaishou public link unavailable"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://v.kuaishou.com/expired", tmp_path)

    assert caught.value.code == "provider_link_unavailable"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_kuaishou_image_post_is_classified_as_unsupported(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(
            b"ERROR: Kuaishou image posts are not supported by the video runner"
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://v.kuaishou.com/image", tmp_path)

    assert caught.value.code == "provider_unsupported"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_facebook_image_post_is_classified_as_unsupported_media(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(
            b"ERROR: Facebook post does not contain a downloadable video"
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://www.facebook.com/share/p/example/", tmp_path)

    assert caught.value.code == "provider_media_unsupported"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_facebook_parse_failure_is_classified_as_extractor_regression(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: [facebook] 123: Cannot parse data"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://www.facebook.com/example/videos/123/", tmp_path)

    assert caught.value.code == "extractor_regression"
    assert caught.value.status == 502


def test_inspection_bounds_playlist_with_overflow_sentinel(tmp_path: Path) -> None:
    configured = settings(tmp_path)
    command = (
        YtDlpCommandBuilder(configured, tmp_path)
        .inspect("https://www.instagram.com/p/example/", cookie_jar=None)
        .argv
    )
    assert "--no-playlist" not in command
    assert command[command.index("--playlist-end") + 1] == str(
        configured.runner_max_gallery_assets + 1
    )


async def test_segment_prefix_probe_bounds_bytes_uses_proxy_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed = {}

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"x" * (40 * 1024)
            pytest.fail("The probe must stop reading at its prefix limit")

        async def aclose(self):
            observed["closed"] = True

    def respond(request):
        assert request.headers["range"] == "bytes=0-8191"
        assert request.headers["referer"] == "https://v.qq.com/x/page/fixture.html"
        return httpx.Response(200, stream=Stream())

    original_client = httpx.AsyncClient

    def client(**kwargs):
        observed["proxy"] = kwargs["proxy"]
        return original_client(transport=httpx.MockTransport(respond))

    class Supervisor(RecordingSupervisor):
        async def run(self, argv, **kwargs):
            assert Path(argv[-1]).read_bytes() == b"x" * (8 * 1024)
            return await super().run(argv, **kwargs)

    monkeypatch.setattr(commands_module.httpx, "AsyncClient", client)
    configured = settings(tmp_path)
    commands = MediaCommands(configured, Supervisor())
    await commands.probe_remote_prefix(
        "https://media.example/first.ts",
        tmp_path,
        referer="https://v.qq.com/x/page/fixture.html",
    )
    assert observed == {"proxy": configured.runner_egress_proxy, "closed": True}
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_guest_cookie_rejection_requests_guest_refresh(tmp_path: Path) -> None:
    config = settings(tmp_path).model_copy(
        update={"runner_access_mode": ProviderAccessMode.GUEST}
    )
    commands = MediaCommands(
        config,
        FailingSupervisor(
            b"ERROR: Fresh cookies (not necessarily logged in) are needed"
        ),
    )
    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect(
            "https://www.douyin.com/video/123",
            tmp_path,
            cookie_jar=tmp_path / "guest.txt",
        )
    assert caught.value.code == "guest_context_required"
    assert caught.value.status == 503


@pytest.mark.asyncio
async def test_platform_without_guest_route_asks_for_a_deployment_session(
    tmp_path: Path,
) -> None:
    # WeChat Channels has no anonymous path: it needs an administrator login.
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(
            b"ERROR: [WeChatChannelsPublic] Fresh cookies are needed to resolve this"
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://weixin.qq.com/sph/Az42YceBcb", tmp_path)

    assert (caught.value.code, caught.value.status) == (
        "provider_session_not_ready",
        503,
    )
