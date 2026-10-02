from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from app.services.downloads.rules.enums import Container
from app.services.provider_failures import FailurePhase
from app.workers.runner import commands as commands_module
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.process import ProcessResult
from app.workers.runner.provider_errors import ProviderFailureContext
from helpers import bound_builder as YtDlpCommandBuilder
from helpers import bound_commands as MediaCommands
from helpers import settings


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
@pytest.mark.parametrize(
    ("sample_state", "cause_code"),
    [
        ("missing", "probe_sample_missing"),
        ("symlink", "probe_sample_symlink"),
        ("broken_symlink", "probe_sample_symlink"),
        ("too_large", "probe_sample_too_large"),
    ],
)
async def test_probe_sample_invalid_output_has_safe_specific_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sample_state: str,
    cause_code: str,
) -> None:
    configured = settings(tmp_path)
    output = tmp_path / "probe-sample.mp4"
    if sample_state in {"symlink", "broken_symlink"}:
        target = tmp_path / "target.mp4"
        if sample_state == "symlink":
            target.write_bytes(b"sample")
        output.symlink_to(target)
    elif sample_state == "too_large":
        with output.open("wb") as stream:
            stream.truncate(configured.runner_max_probe_sample_bytes + 1)
    commands = MediaCommands(configured, RecordingSupervisor())
    successful_download = AsyncMock(
        return_value=ProcessResult(0, b"", b"", False, False)
    )
    monkeypatch.setattr(commands, "_run", successful_download)

    with pytest.raises(RunnerFailure) as caught:
        await commands.download_probe_sample(
            "https://t.me/europa_press/18586", "0", output, tmp_path
        )

    error = caught.value.during(FailurePhase.PROBE_MEDIA)
    assert (error.code, error.status, error.failure.gate, error.failure.stage) == (
        "inspection_failed",
        502,
        "②",
        "validate",
    )
    assert error.failure.evidence == {
        "kind": "local_validation",
        "cause_code": cause_code,
    }
    argv = successful_download.call_args.args[0]
    assert argv[argv.index("--max-filesize") + 1] == str(
        configured.runner_max_probe_sample_bytes
    )
    assert successful_download.call_args.kwargs["workspace_limit_bytes"] == (
        configured.runner_max_probe_sample_bytes
    )


@pytest.mark.asyncio
async def test_probe_sample_at_size_limit_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = settings(tmp_path)
    output = tmp_path / "probe-sample.mp4"
    with output.open("wb") as stream:
        stream.truncate(configured.runner_max_probe_sample_bytes)
    commands = MediaCommands(configured, RecordingSupervisor())
    monkeypatch.setattr(
        commands,
        "_run",
        AsyncMock(return_value=ProcessResult(0, b"", b"", False, False)),
    )

    await commands.download_probe_sample(
        "https://t.me/europa_press/18586", "0", output, tmp_path
    )


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


def test_inspection_has_no_hidden_retries_and_transfer_keeps_fragment_budget(
    tmp_path: Path,
) -> None:
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

    for command, expected in zip(commands, ("0", "0", "0", "3"), strict=True):
        assert "--no-warnings" not in command
        for option in ("--retries", "--fragment-retries"):
            assert command.count(option) == 1
            assert command[command.index(option) + 1] == expected
        assert command.count("--extractor-retries") == 1
        assert command[command.index("--extractor-retries") + 1] == "0"

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


@pytest.mark.parametrize("load_info", [False, True])
def test_dailymotion_download_aborts_missing_fragments_with_either_handoff(
    tmp_path: Path, load_info: bool
) -> None:
    builder = YtDlpCommandBuilder(settings(tmp_path), tmp_path)
    info_json = tmp_path / "resolved.info.json" if load_info else None
    command = builder.download(
        "https://dai.ly/xsynthetic1",
        "hls-720",
        tmp_path / "video.input",
        max_bytes=1024,
        cookie_jar=None,
        info_json=info_json,
    ).argv
    assert command.count("--abort-on-unavailable-fragments") == 1
    assert "--skip-unavailable-fragments" not in command
    assert ("--load-info-json" in command) is load_info
    assert "--cookies" not in command
    other = builder.download(
        "https://vimeo.com/123",
        "http-540p",
        tmp_path / "other.input",
        max_bytes=1024,
        cookie_jar=None,
        info_json=info_json,
    ).argv
    assert "--abort-on-unavailable-fragments" not in other


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

    assert caught.value.code == "rate_limited"
    assert caught.value.status == 429


@pytest.mark.asyncio
async def test_ambiguous_rate_limit_or_login_hint_is_unclassified(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: rate-limit reached or login required"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://x.com/example/status/123", tmp_path)

    assert caught.value.code == "extractor_broken"
    assert caught.value.status == 502


@pytest.mark.asyncio
async def test_local_media_probe_does_not_depend_on_youtube_pot_provider(
    tmp_path: Path,
):
    supervisor = RecordingSupervisor()

    async def unavailable(*_args):
        raise AssertionError("local ffprobe cannot require a PO Token provider")

    configured = settings(tmp_path).model_copy(
        update={
            "runner_youtube_pot_base_url": "http://youtube-pot-provider:4416",
        }
    )
    commands = MediaCommands(configured, supervisor, pot_provider_probe=unavailable)
    await commands.probe(
        tmp_path / "artifact.mp4",
        tmp_path,
        failure_context=ProviderFailureContext(
            "youtube", "https://youtu.be/owned", True
        ),
    )
    assert supervisor.argv[0] == "ffprobe"


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

    assert caught.value.code == "transient"
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

    assert caught.value.code == "challenge"
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
@pytest.mark.parametrize("returncode", [0, 1])
@pytest.mark.parametrize("reason", ["Private video", "非公開動画"])
async def test_youtube_private_content_precedes_login_and_extractor_failure(
    tmp_path: Path, returncode: int, reason: str
) -> None:
    stderr = (
        f"WARNING: [youtube] s7_qI6_mIXc: {reason}\n"
        "WARNING: LOGIN_REQUIRED; HTTP Error 429; Unable to extract player response"
    ).encode()
    supervisor = (
        FailingSupervisor(stderr)
        if returncode
        else SuccessfulWarningSupervisor(b'{"id":"s7_qI6_mIXc","formats":[]}', stderr)
    )
    commands = MediaCommands(settings(tmp_path), supervisor)
    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://www.youtube.com/watch?v=s7_qI6_mIXc", tmp_path)
    failure = caught.value.failure
    assert caught.value.code == "content_unavailable"
    assert failure.gate == "none"
    assert failure.stage == "resolve"
    assert failure.evidence["kind"] == "upstream_response"
    assert reason not in str(failure.evidence)


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

    assert caught.value.code == "rate_limited"
    assert caught.value.status == 429


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

    assert caught.value.code == "network_blocked"
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

    assert caught.value.code == "content_unavailable"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_ambiguous_youtube_unavailable_does_not_prove_deletion(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: [youtube] pqyXR30AoOs: Video unavailable"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://youtu.be/pqyXR30AoOs", tmp_path)

    assert caught.value.code == "extractor_broken"
    assert caught.value.status == 502


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

    assert caught.value.code == "rate_limited"
    assert caught.value.status == 429


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("terminal_error", "expected_code", "expected_status"),
    (
        (b"ERROR: This video is DRM protected", "content_protected", 422),
        (b"ERROR: This video is private", "content_unavailable", 403),
        (
            b"ERROR: This video is not available in your country",
            "rate_limited",
            429,
        ),
        (
            b"ERROR: Account cookies are no longer valid",
            "rate_limited",
            429,
        ),
        (b"ERROR: Fresh cookies are needed", "rate_limited", 429),
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

    assert caught.value.code == "rate_limited"
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

    assert caught.value.code == "login_required"
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

    assert caught.value.code == "content_protected"
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

    assert caught.value.code == "content_unavailable"
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

    assert caught.value.code == "transient"
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

    assert caught.value.code == "extractor_broken"
    assert caught.value.status == 502


@pytest.mark.asyncio
async def test_anonymous_youtube_media_403_does_not_prove_a_challenge(
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

    assert caught.value.code == "network_blocked"
    assert caught.value.status == 502


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

    assert caught.value.code == "challenge"
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

    assert caught.value.code == "runtime_unavailable"
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

    assert caught.value.code == "network_blocked"
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

    assert caught.value.code == "content_unavailable"
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

    assert caught.value.code == "content_unavailable"
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

    assert caught.value.code == "login_required"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_youtube_uses_operator_managed_provider_egress(tmp_path: Path) -> None:
    supervisor = RecordingSupervisor()
    configured = settings(tmp_path).model_copy(
        update={"runner_global_egress_proxy": "http://youtube-egress:3128"}
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
    probe_calls: list[str] = []

    async def healthy_probe(base_url: str) -> bool:
        probe_calls.append(base_url)
        return True

    configured = settings(tmp_path).model_copy(
        update={
            "runner_youtube_pot_base_url": "http://youtube-pot-provider:4416",
            "runner_youtube_pot_provider_version": "unrestricted-diagnostic-version",
        }
    )
    commands = MediaCommands(
        configured,
        supervisor,
        pot_provider_probe=healthy_probe,
    )

    await commands.inspect("https://www.youtube.com/watch?v=owned", tmp_path)

    assert probe_calls == ["http://youtube-pot-provider:4416"]
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

    async def unavailable_probe(_base_url: str) -> bool:
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

    assert caught.value.code == "runtime_unavailable"
    assert caught.value.status == 503
    assert supervisor.argv == ()


@pytest.mark.asyncio
async def test_youtube_failure_rechecks_pot_after_process_spawn(tmp_path: Path) -> None:
    supervisor = FailingSupervisor(b"ERROR: Sign in to confirm you're not a bot")
    outcomes = iter((True, False))

    async def lifecycle_probe(_base_url: str) -> bool:
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

    assert caught.value.code == "runtime_unavailable"
    assert caught.value.status == 503


@pytest.mark.asyncio
async def test_non_youtube_command_does_not_probe_pot_provider(tmp_path: Path) -> None:
    supervisor = RecordingSupervisor()

    async def unexpected_probe(_base_url: str) -> bool:
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
            return httpx.Response(302, json={"version": "1.3.2"})

    monkeypatch.setattr(commands_module.httpx, "AsyncClient", Client)

    assert (
        await commands_module._pot_provider_ready(
            "http://youtube-pot-provider:4416",
        )
        is False
    )
    assert options == {
        "timeout": 2.0,
        "trust_env": False,
        "follow_redirects": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b"", b"not-json", b'{"version":"1.3.1"}'])
async def test_pot_health_probe_does_not_require_release_identity(
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
) -> None:
    class Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get(self, _url: str) -> httpx.Response:
            return httpx.Response(200, content=payload)

    monkeypatch.setattr(commands_module.httpx, "AsyncClient", Client)

    assert await commands_module._pot_provider_ready(
        "http://youtube-pot-provider:4416",
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

    assert caught.value.code == "invalid_input"
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

    assert caught.value.code == "invalid_input"


@pytest.mark.asyncio
async def test_non_ytdlp_failures_keep_their_original_code(tmp_path: Path) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ffprobe exited with status 1"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.probe_remote("https://media.example/video", tmp_path)

    assert caught.value.code == "media_probe_failed"
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

    assert caught.value.code == "network_blocked"
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

    assert caught.value.code == "network_blocked"
    assert caught.value.status == 502


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

    assert caught.value.code == "content_unavailable"
    assert caught.value.status == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stderr", "expected_code", "expected_status"),
    (
        (
            b"ERROR: Douyin official share link temporarily unavailable",
            "transient",
            503,
        ),
        (
            b"ERROR: Douyin official share link response structure changed",
            "extractor_broken",
            502,
        ),
        (
            b"ERROR: Douyin official share link verification required",
            "challenge",
            422,
        ),
        (
            b"ERROR: Douyin official share link rate limited",
            "rate_limited",
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

    assert caught.value.code == "invalid_input"
    assert caught.value.status == 422


@pytest.mark.asyncio
async def test_xhs_missing_initial_state_is_structure_failure(
    tmp_path: Path,
) -> None:
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: Unable to extract initial state"),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://xhslink.com/m/expired", tmp_path)

    assert caught.value.code == "extractor_broken"
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

    assert caught.value.code == "content_unavailable"
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

    assert caught.value.code == "challenge"
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

    assert caught.value.code == "extractor_broken"
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

    assert caught.value.code == "content_unavailable"
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

    assert caught.value.code == "content_unavailable"
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

    assert caught.value.code == "invalid_input"
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

    assert caught.value.code == "invalid_input"
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

    assert caught.value.code == "extractor_broken"
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
async def test_platform_cookie_hint_is_client_challenge(
    tmp_path: Path,
) -> None:
    # Cookie text does not establish the selected route or session state.
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(
            b"ERROR: [WeChatChannelsPublic] Fresh cookies are needed to resolve this"
        ),
    )

    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://weixin.qq.com/sph/Az42YceBcb", tmp_path)

    assert (caught.value.code, caught.value.status) == (
        "challenge",
        502,
    )


async def test_command_rate_limit_preserves_retry_after_and_structured_evidence(
    tmp_path,
):
    commands = MediaCommands(
        settings(tmp_path),
        FailingSupervisor(b"ERROR: HTTP Error 429: Too Many Requests\nRetry-After: 12"),
    )
    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://vimeo.com/1", tmp_path)
    assert caught.value.code == "rate_limited" and caught.value.status == 429
    assert caught.value.failure.retry_after is not None
    assert caught.value.failure.evidence == {
        "kind": "upstream_response",
        "returncode": 1,
        "stderr_truncated": False,
        "http_status": 429,
    }


@pytest.mark.parametrize("clear", [False, True])
async def test_drm_warning_does_not_hide_a_clear_format(tmp_path, clear):
    import json

    formats = [
        {"format_id": "drm", "url": "https://media.example/drm", "has_drm": True}
    ]
    if clear:
        formats.append(
            {
                "format_id": "clear",
                "url": "https://media.example/clear",
                "has_drm": False,
            }
        )
    commands = MediaCommands(
        settings(tmp_path),
        SuccessfulWarningSupervisor(
            json.dumps({"id": "sample", "formats": formats}).encode(),
            b"WARNING: This format is DRM protected",
        ),
    )
    if clear:
        payload = await commands.inspect("https://youtu.be/jNQXAC9IVRw", tmp_path)
        assert payload["formats"] == formats
    else:
        with pytest.raises(RunnerFailure, match="content protected"):
            await commands.inspect("https://youtu.be/jNQXAC9IVRw", tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("returncode", [0, 1])
@pytest.mark.parametrize("explicit", [True, False])
async def test_ambiguous_youtube_failure_uses_affirmative_anonymous_evidence(
    monkeypatch, tmp_path, returncode, explicit
):
    calls = []

    async def evidence(request, ctx):
        calls.append((request.profile.key, ctx.egress.proxy_url))
        return explicit

    monkeypatch.setattr(commands_module, "explicit_content_restriction", evidence)
    stderr = b"WARNING: [youtube] Video unavailable"
    supervisor = (
        FailingSupervisor(stderr)
        if returncode
        else SuccessfulWarningSupervisor(b'{"id":"s7_qI6_mIXc","formats":[]}', stderr)
    )
    commands = MediaCommands(settings(tmp_path), supervisor)
    with pytest.raises(RunnerFailure) as caught:
        await commands.inspect("https://www.youtube.com/watch?v=s7_qI6_mIXc", tmp_path)
    assert caught.value.code == (
        "content_unavailable" if explicit else "extractor_broken"
    )
    assert caught.value.failure.gate == "none"
    if explicit:
        assert (
            caught.value.failure.evidence["cause_code"]
            == "explicit_public_player_restriction"
        )
    assert len(calls) == 1


async def test_terminal_packet_remux_is_exact_copy_without_noise_or_reencoding(
    tmp_path,
):
    supervisor = RecordingSupervisor()
    commands = MediaCommands(settings(tmp_path), supervisor)
    await commands.remux(
        (tmp_path / "input.mp4",),
        tmp_path / "artifact.mp4",
        Container.MP4,
        tmp_path,
        drop_video_packet=(1234, 1841),
    )
    argv = supervisor.argv
    assert argv[argv.index("-c") + 1] == "copy"
    assert (
        argv[argv.index("-bsf:v") + 1]
        == "noise=amount=0:drop=eq(pos\\,1234)*eq(size\\,1841)"
    )
    assert "0:a:0" in argv
    assert "-err_detect" not in argv


@pytest.mark.parametrize("position,size", [(-1, 1), (1, 0), (True, 1), (1, False)])
async def test_terminal_packet_filter_cannot_accept_arbitrary_expressions(
    tmp_path, position, size
):
    supervisor = RecordingSupervisor()
    commands = MediaCommands(settings(tmp_path), supervisor)
    with pytest.raises(RunnerFailure) as caught:
        await commands.remux(
            (tmp_path / "input.mp4",),
            tmp_path / "artifact.mp4",
            Container.MP4,
            tmp_path,
            drop_video_packet=(position, size),
        )
    assert caught.value.code == "invalid_input"
    assert supervisor.argv == ()


async def test_terminal_packet_probe_is_local_and_limited_to_tail_video(tmp_path):
    supervisor = RecordingSupervisor()
    commands = MediaCommands(settings(tmp_path), supervisor)
    await commands.probe_terminal_packets(
        tmp_path / "input.mp4",
        tmp_path,
        start_seconds=28.123456,
        failure_context=ProviderFailureContext(
            "youku", "https://v.youku.com/v_show/id_fixture.html", True
        ),
    )
    argv = supervisor.argv
    assert argv[argv.index("-protocol_whitelist") + 1] == "file"
    assert argv[argv.index("-select_streams") + 1] == "v:0"
    assert argv[argv.index("-read_intervals") + 1] == "28.123456%"
    assert "packet=pos,size,pts_time,flags" in argv
