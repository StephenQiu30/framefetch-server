"""WPC dispatch, provider isolation and private browser lifecycle."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from app.workers.runner.commands import MediaCommands
from app.workers.runner.engine import identity
from app.workers.runner.engine.browser import youtube
from app.workers.runner.engine.layers.browser import BrowserLayer
from app.workers.runner.engine.layers.http import HttpLayer
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.process import ProcessResult
from app.workers.runner.provider_registry import provider_request
from app.workers.runner.service import MediaRunnerService
from app.workers.runner.youtube_proof import main
from helpers import run_context, settings, split_media_info
from test_engine_skeleton import source_for
from test_p1_wiring import resolved


async def test_youtube_dispatch_keeps_egress_without_playwright(tmp_path, monkeypatch):
    service = MediaRunnerService(settings(tmp_path))
    source = source_for(service, tmp_path)
    request = provider_request("https://youtu.be/jNQXAC9IVRw")
    source = replace(
        source,
        request=request,
        execution_context=replace(service._context(request), resolved_layer="L3"),
    )
    calls = []

    async def http(self, item, ctx):
        calls.append((item.execution_context, ctx))
        return resolved(ctx, client=item.execution_context.client)

    monkeypatch.setattr(HttpLayer, "resolve", http)
    try:
        media = await BrowserLayer().resolve(source, source.run_context)
        assert media.client == youtube.CLIENT
        assert calls[0][1] is source.run_context
        assert calls[0][0].resolved_layer == "L3"
        with pytest.raises(RunnerFailure, match="context changed"):
            await BrowserLayer().resolve(
                replace(
                    source,
                    expected_context=replace(
                        source.execution_context, client="youtube:tv"
                    ),
                ),
                source.run_context,
            )
    finally:
        source.workspace.cleanup()


@pytest.mark.parametrize("mode", ["bgutil", "wpc"])
def test_only_selected_provider_is_constructed(monkeypatch, mode):
    import yt_dlp
    import yt_dlp.plugins
    from yt_dlp.extractor.youtube.pot._registry import _pot_providers

    monkeypatch.setattr(yt_dlp.plugins, "load_all_plugins", lambda: None)
    monkeypatch.setattr(
        _pot_providers,
        "value",
        {"WPC": object(), "BgUtilHTTP": object(), "BgUtilScript": object()},
    )
    seen = []

    class Downloader(yt_dlp.YoutubeDL):
        def __init__(self, options):
            seen.append(set(_pot_providers.value))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def download(self, urls):
            assert urls == ["https://youtu.be/jNQXAC9IVRw"]
            return 0

        def download_with_info_file(self, path):
            assert path == "/work/info.json"
            return 0

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Downloader)
    assert (
        main(
            [mode, "--ignore-config", "--skip-download", "https://youtu.be/jNQXAC9IVRw"]
        )
        == 0
    )
    assert seen == [{"WPC"} if mode == "wpc" else {"BgUtilHTTP"}]
    assert main([mode, "--ignore-config", "--load-info-json", "/work/info.json"]) == 0


@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
async def test_wpc_supervision_tmpfs_proxy_and_cleanup(tmp_path, monkeypatch, outcome):
    root = tmp_path / "identity"
    monkeypatch.setattr(identity, "COOKIE_TMPFS_ROOT", root)
    config = settings(tmp_path).model_copy(update={"runner_browser_temp_root": root})
    ctx = run_context(config, "youtube")
    calls = []

    class Supervisor:
        async def run(self, command, *, env, **kwargs):
            calls.append((command, env))
            private = Path(env["TMPDIR"])
            assert private.is_relative_to(root)
            assert private.stat().st_mode & 0o777 == 0o700
            (private / "browser-state").write_text("ephemeral")
            if outcome == "cancelled":
                raise asyncio.CancelledError
            return ProcessResult(
                0 if outcome == "success" else 1,
                json.dumps(split_media_info()).encode(),
                b"failure",
                False,
                False,
            )

    async def unavailable(url):
        pytest.fail("WPC must not depend on bgutil health")

    commands = (
        MediaCommands(
            config.model_copy(
                update={"runner_youtube_pot_base_url": "http://pot:4416"}
            ),
            Supervisor(),
            pot_provider_probe=unavailable,
        )
        .with_context(ctx)
        .with_client(youtube.CLIENT)
    )
    if outcome == "success":
        await commands.inspect("https://youtu.be/jNQXAC9IVRw", tmp_path)
    else:
        with pytest.raises(
            asyncio.CancelledError if outcome == "cancelled" else RunnerFailure
        ):
            await commands.inspect("https://youtu.be/jNQXAC9IVRw", tmp_path)
    command, env = calls[0]
    assert command[:2] == ("xvfb-run", "-a")
    assert "wpc" in command and "youtube:player_client=mweb" in command
    assert (
        "youtubepot-wpc:browser_path=/usr/local/bin/framefetch-wpc-chromium" in command
    )
    assert command[command.index("--proxy") + 1] == ctx.egress.proxy_url
    assert env["HTTPS_PROXY"] == ctx.egress.proxy_url
    assert env["HOME"] == env["TMPDIR"]
    assert env["NO_PROXY"] == env["no_proxy"] == "127.0.0.1,localhost"
    assert not Path(env["TMPDIR"]).exists() and not list(root.iterdir())
